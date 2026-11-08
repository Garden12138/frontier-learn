"""Explicit public GET trial, excluded from automatic offline collection by file name.

A passing observer test means a truthful result was recorded, not necessarily successful sync.
The application/worker uses its real GitHub connector; concept questions use Fake only.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import Settings
from app.domain.concept_assessment import concept_handler
from app.domain.knowledge_sync import sync_handler
from app.domain.tutor import tutor_handler
from app.jobs.service import run_one
from app.persistence.models import KnowledgeEvidence, SourceDocument
from tests.concept_fixture import BrowserConceptProvider
from tests.conftest import TestDatabase
from tests.integration.test_concept_check import concept_client as concept_client
from tests.integration.test_concept_check import request_question
from tests.integration.test_model_budget import consent
from tests.planning_fixture import authenticate, generate, make_goal
from tests.test_citations import create


async def test_record_real_public_notes_sync(concept_client: AsyncClient, pg: TestDatabase) -> None:
    assert os.environ.get("FRONTIER_LIVE_NOTES_CHECK") == "true", (
        "Explicit public GET opt-in required"
    )
    client = concept_client
    headers = await authenticate(client, "public-notes-trial")
    goal = await make_goal(
        client,
        headers,
        title="理解 Self-Attention，进一步学习 MHA/MQA/GQA",
        priorities=["自注意力", "MHA", "MQA", "GQA"],
    )
    initial_plan = await generate(client, headers, goal)
    source = await client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "external_ref": "Garden12138/notes",
            "consent": True,
            "path_prefixes": ["ai/book_note/Build-A-Large-Language-Mode notebook/"],
        },
    )
    assert source.status_code == 201

    async def synchronize() -> dict[str, object]:
        response = await client.post(
            f"/api/v1/sources/{source.json()['id']}/sync",
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 202
        await run_one(pg.factory, {"GITHUB_SYNC": sync_handler(pg.factory, Settings())})
        job_id = response.json()["id"]
        result: dict[str, object] = (
            await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        ).json()
        return result

    result = await synchronize()
    documents = (
        await client.get(f"/api/v1/sources/{source.json()['id']}/documents", headers=headers)
    ).json()
    report: dict[str, object] = {
        "observed_at": datetime.now(UTC).isoformat(),
        "mode": "REAL_APPLICATION_CONNECTOR_NO_CREDENTIALS_FAKE_QUESTIONS",
        "source": source.json(),
        "job": result,
        "documents": documents,
        "live_sync_passed": result["status"] == "SUCCEEDED",
        "before_import": initial_plan.model_dump(mode="json"),
    }
    if result["status"] == "SUCCEEDED":
        profile = (await client.get("/api/v1/knowledge?limit=500", headers=headers)).json()
        assert all(row["level"] == "EXPOSED" and row["confidence"] == "LOW" for row in profile)
        async with pg.factory() as db:
            evidence = list(await db.scalars(select(KnowledgeEvidence)))
            document_rows = list(await db.scalars(select(SourceDocument)))
            by_id = {document.id: document for document in document_rows}
            for item in evidence:
                assert item.document_id
                document = by_id[item.document_id]
                assert document.content_text
                locator = item.source_locator
                assert (
                    locator["commit_sha"] == document.revision and locator["path"] == document.path
                )
                start, end = int(str(locator["line_start"])), int(str(locator["line_end"]))
                assert item.excerpt in "".join(
                    document.content_text.splitlines(keepends=True)[start - 1 : end]
                )
            note = next(
                document
                for document in document_rows
                if document.path.endswith("/Implement self-attention.md")
            )
            assert note.content_text
            passage = next(
                part
                for part in note.content_text.split("\n\n")
                if "self" in part and "注意力权重" in part
            )
            evidence_count = len(evidence)
        second_sync = await synchronize()
        async with pg.factory() as db:
            assert len(list(await db.scalars(select(KnowledgeEvidence)))) == evidence_count
            assert len(list(await db.scalars(select(SourceDocument)))) == len(documents)
        assert second_sync["status"] == "SUCCEEDED"
        imported = await generate(client, headers, goal, initial_plan.revision_no)
        report.update(
            {
                "profile": profile,
                "evidence_count": evidence_count,
                "repeat_sync": second_sync,
                "after_import": imported.model_dump(mode="json"),
            }
        )
        await consent(client, headers, True)
        rounds = []
        revision = imported.revision_no
        for choice in ("C", "A"):
            session = await create(
                client,
                headers,
                goal_id=str(goal.id),
                page={
                    "url": "",
                    "title": "真实同步笔记的自注意力片段",
                    "provider": "MANUAL",
                    "scope": "MANUAL",
                    "blocks": [
                        {"id": "b0", "heading": "自注意力", "text": passage, "selector": ""}
                    ],
                    "selection": {"block_id": "b0", "quote": passage},
                },
            )
            await run_one(pg.factory, {"TUTOR_GUIDE": tutor_handler(pg.factory)})
            pending = await request_question(client, headers, session.id)
            await run_one(
                pg.factory,
                {
                    "ASSESSMENT_QUESTION": concept_handler(
                        pg.factory, BrowserConceptProvider(), Settings()
                    )
                },
            )
            ready = (
                await client.get(f"/api/v1/assessments/{pending['id']}", headers=headers)
            ).json()
            answered = (
                await client.post(
                    f"/api/v1/assessments/{pending['id']}/answer",
                    headers=headers,
                    json={"version": ready["version"], "choice": choice},
                )
            ).json()
            current_plan = (
                await client.get(f"/api/v1/plans/{imported.id}", headers=headers)
            ).json()
            assert current_plan["revision_no"] == revision
            confirmed = (
                await client.post(
                    f"/api/v1/assessments/{pending['id']}/confirm",
                    headers=headers,
                    json={"version": answered["version"], "confirm": True},
                )
            ).json()
            draft = await client.post(
                "/api/v1/artifacts", headers=headers, json={"assessment_id": pending["id"]}
            )
            assert draft.status_code == 201
            next_plan = await generate(client, headers, goal, confirmed["plan_revision"])
            revision = next_plan.revision_no
            assert next_plan.tasks[0].kind == ("CHECK" if choice == "C" else "REVIEW")
            history = (
                await client.get(f"/api/v1/plans/{imported.id}/revisions", headers=headers)
            ).json()
            assert any(pending["id"] in row["rationale"] for row in history)
            rounds.append(
                {
                    "assessment_id": pending["id"],
                    "result": answered["feedback"],
                    "next_task": next_plan.tasks[0].model_dump(mode="json"),
                    "history": history,
                }
            )
        report["rounds"] = rounds
        report["questions"] = "FAKE_NOT_A_REAL_MODEL_OR_HUMAN_TEST"
    else:
        assert result["status"] in {"FAILED", "PARTIAL"} and result["error_code"]
    output = Path(__file__).parents[4] / "test-results/v0.1.1"
    output.mkdir(parents=True, exist_ok=True)
    (output / "live-notes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
