"""Offline replay of a pinned public note. No live-network or learning-effect claim."""

import json
from pathlib import Path
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import Settings
from app.domain.concept_assessment import concept_handler
from app.domain.tutor import tutor_handler
from app.jobs.service import run_one
from app.persistence.models import KnowledgeEvidence
from tests.concept_fixture import BrowserConceptProvider
from tests.conftest import TestDatabase
from tests.github_fixture import GitHubFixture, blob_sha
from tests.integration.test_concept_check import concept_client as concept_client
from tests.integration.test_concept_check import request_question
from tests.integration.test_github_ingest import synchronize
from tests.integration.test_model_budget import consent
from tests.planning_fixture import authenticate, generate, make_goal
from tests.test_citations import create

FIXTURES = Path(__file__).parents[1] / "fixtures/real-notes"


async def test_pinned_notes_import_and_two_learning_rounds(
    concept_client: AsyncClient, pg: TestDatabase
) -> None:
    client = concept_client
    headers = await authenticate(client)
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    note = (FIXTURES / "self-attention.txt").read_bytes()
    code = (FIXTURES / "chapter03_attention.txt").read_bytes()
    assert blob_sha(note) == provenance["blob_sha"]
    code_sha = "c0c95ce8086cf3966ced015631bf0a1102cfa685"
    assert blob_sha(code) == code_sha
    goal = await make_goal(
        client,
        headers,
        title="理解 Self-Attention，进一步学习 MHA/MQA/GQA",
        priorities=["自注意力", "MHA", "MQA", "GQA"],
    )
    before = await generate(client, headers, goal)
    assert before.tasks[0].kind == "EXPLORE"
    source = (
        await client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "external_ref": "Garden12138/notes",
                "consent": True,
                "path_prefixes": ["ai/book_note/Build-A-Large-Language-Mode notebook/"],
            },
        )
    ).json()
    code_path = (
        "ai/book_note/Build-A-Large-Language-Mode notebook/code/examples/chapter03_attention.py"
    )
    fixture = GitHubFixture({provenance["path"]: note, code_path: code})
    fixture.revision = provenance["revision"]
    assert (
        await synchronize(client, pg, headers, UUID(source["id"]), fixture)
    ).status == "SUCCEEDED"
    profile = (await client.get("/api/v1/knowledge?limit=500", headers=headers)).json()
    assert profile and all(
        row["level"] == "EXPOSED" and row["confidence"] == "LOW" for row in profile
    )
    all_evidence = []
    for state in profile:
        evidence = (
            await client.get(f"/api/v1/knowledge/{state['concept_id']}/evidence", headers=headers)
        ).json()
        for item in evidence:
            location = item["source_locator"]
            assert location["commit_sha"] == provenance["revision"]
            original = fixture.files[location["path"]].decode()
            assert item["excerpt"] in "".join(
                original.splitlines(keepends=True)[
                    location["line_start"] - 1 : location["line_end"]
                ]
            )
        all_evidence.extend(evidence)
    assert {item["kind"] for item in all_evidence} >= {"OBSERVED_NOTE", "CODE_ARTIFACT"}
    assert (
        await synchronize(client, pg, headers, UUID(source["id"]), fixture)
    ).status == "SUCCEEDED"
    async with pg.factory() as db:
        assert len(list(await db.scalars(select(KnowledgeEvidence)))) == len(all_evidence)
    imported = await generate(client, headers, goal, before.revision_no)
    assert imported.tasks[0].kind == "CHECK" and imported.tasks[0].evidence_ids
    await consent(client, headers, True)
    # Read a real passage, retain its exact text, and exercise public APIs only for learning state.
    passage = next(
        part for part in note.decode().split("\n\n") if "self" in part and "注意力权重" in part
    )
    rounds = []
    revision = imported.revision_no
    for choice in ("C", "A"):
        session = await create(
            client,
            headers,
            goal_id=str(goal.id),
            page={
                "url": "",
                "title": "公开笔记固定快照 · 自注意力",
                "provider": "MANUAL",
                "scope": "MANUAL",
                "blocks": [{"id": "b0", "heading": "自注意力", "text": passage, "selector": ""}],
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
        ready = (await client.get(f"/api/v1/assessments/{pending['id']}", headers=headers)).json()
        answered = (
            await client.post(
                f"/api/v1/assessments/{pending['id']}/answer",
                headers=headers,
                json={"version": ready["version"], "choice": choice},
            )
        ).json()
        assert answered["feedback"]["result"] == ("SUPPORTED" if choice == "C" else "NEEDS_REVIEW")
        unconfirmed = (await client.get(f"/api/v1/plans/{imported.id}", headers=headers)).json()
        assert unconfirmed["revision_no"] == revision
        confirmed = (
            await client.post(
                f"/api/v1/assessments/{pending['id']}/confirm",
                headers=headers,
                json={"version": answered["version"], "confirm": True},
            )
        ).json()
        revision = confirmed["plan_revision"]
        draft = await client.post(
            "/api/v1/artifacts", headers=headers, json={"assessment_id": pending["id"]}
        )
        assert draft.status_code == 201 and "尚未独立核验" in draft.json()["markdown"]
        next_plan = await generate(client, headers, goal, revision)
        revision = next_plan.revision_no
        assert next_plan.tasks[0].kind == ("CHECK" if choice == "C" else "REVIEW")
        assert next_plan.tasks[0].id != imported.tasks[0].id
        history = (
            await client.get(f"/api/v1/plans/{imported.id}/revisions", headers=headers)
        ).json()
        assert any(pending["id"] in item["rationale"] for item in history)
        rounds.append(
            {
                "assessment_id": pending["id"],
                "result": answered["feedback"],
                "next_task": next_plan.tasks[0].model_dump(mode="json"),
                "history": history,
            }
        )
    profile_after = (await client.get("/api/v1/knowledge?limit=500", headers=headers)).json()
    assert all(row["level"] == "EXPOSED" and row["confidence"] == "LOW" for row in profile_after)
    report = {
        "mode": "OFFLINE_PINNED_PUBLIC_SNAPSHOT_FAKE_MODEL_NOT_HUMAN",
        "provenance": provenance,
        "profile": profile,
        "evidence_count": len(all_evidence),
        "before": before.model_dump(mode="json"),
        "after_import": imported.model_dump(mode="json"),
        "rounds": rounds,
    }
    output = Path(__file__).parents[4] / "test-results/v0.1.1"
    output.mkdir(parents=True, exist_ok=True)
    (output / "two-rounds.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
