import pytest

from app.connectors.base import DocumentRef, SourceScope
from app.connectors.github import GitHubConnector, repository_ref
from app.core.errors import Problem
from app.ingestion.evidence import extract_candidates
from app.ingestion.markdown import parse_text
from tests.github_fixture import GitHubFixture, blob_sha


async def test_tree_fallback_ignores_builds_and_verifies_blob() -> None:
    fixture = GitHubFixture(
        {
            "notes/BPE.md": b"# BPE\n\nToken pairs.",
            "node_modules/package.md": b"ignore",
            "binary.png": b"PNG",
        }
    )
    fixture.truncated = True
    connector = GitHubConnector("learner/notes", reader=fixture)
    snapshot = await connector.snapshot(SourceScope("learner/notes"))
    assert [f.path for f in snapshot.documents] == ["notes/BPE.md"]
    assert snapshot.ignored_count == 2
    assert (
        await connector.read_document(SourceScope("learner/notes"), snapshot.documents[0])
        == fixture.files["notes/BPE.md"]
    )
    with pytest.raises(Problem, match="SOURCE_SCOPE_DENIED"):
        await connector.snapshot(SourceScope("other/repo"))


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "GITHUB_ACCESS_DENIED"),
        (403, "GITHUB_ACCESS_DENIED"),
        (404, "GITHUB_ACCESS_DENIED"),
        (429, "GITHUB_RATE_LIMIT"),
        (409, "EMPTY_REPOSITORY"),
        (503, "GITHUB_UNAVAILABLE"),
        (301, "REPOSITORY_MOVED"),
    ],
)
async def test_github_failures_are_safe(status: int, code: str) -> None:
    fixture = GitHubFixture({})
    fixture.status = status
    with pytest.raises(Problem) as error:
        await GitHubConnector("learner/notes", reader=fixture).snapshot(
            SourceScope("learner/notes")
        )
    assert error.value.code == code
    assert "PRIVATE" not in error.value.message


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.com/a/b",
        "https://github.com@evil.com/a/b",
        "https://github.com:999/a/b",
        "a/..",
        "a/b/c",
        "a\\b/repo",
    ],
)
def test_repository_urls_are_strict(value: str) -> None:
    with pytest.raises(Problem):
        repository_ref(value)
    assert repository_ref("https://github.com/Learner/Notes.git") == "learner/notes"


def test_markdown_offsets_and_generic_concepts_are_exact() -> None:
    raw = (
        "# 园艺基础\r\n\r\nGQA is only mentioned.\r\n\r\n```python\r\nprint('never run')\r\n```\r\n"
    ).encode()
    text, chunks = parse_text(raw)
    for chunk in chunks:
        assert text[chunk.start : chunk.end] == chunk.text
        assert chunk.line_start >= 1
        assert chunk.line_end >= chunk.line_start
    assert any(c.content_type == "CODE" for c in chunks)
    candidates = extract_candidates("garden.md", text, chunks)
    assert {c.canonical_name for c in candidates} >= {"园艺基础", "gqa"}
    assert all(c.kind in {"OBSERVED_NOTE", "CODE_ARTIFACT"} for c in candidates)
    with pytest.raises(Problem, match="UNSUPPORTED_ENCODING"):
        parse_text(b"\xff\xfe")


async def test_batch_file_limit_refuses_incomplete_import() -> None:
    fixture = GitHubFixture({f"note{i}.md": f"# Note {i}".encode() for i in range(201)})
    with pytest.raises(Problem, match="BATCH_FILE_LIMIT"):
        await GitHubConnector("learner/notes", reader=fixture).snapshot(
            SourceScope("learner/notes")
        )


async def test_folder_scope_is_applied_before_size_limits_and_blob_reads() -> None:
    fixture = GitHubFixture(
        {
            **{f"outside/note{i}.md": b"# Outside" for i in range(201)},
            "notes/one.md": b"# Scoped\n\nSelected text.",
        }
    )
    connector = GitHubConnector("learner/notes", reader=fixture)
    scope = SourceScope("learner/notes", ("notes/",))
    snapshot = await connector.snapshot(scope)
    assert [document.path for document in snapshot.documents] == ["notes/one.md"]
    outside = DocumentRef("outside/note0.md", blob_sha(b"# Outside"), len(b"# Outside"))
    with pytest.raises(Problem, match="DOCUMENT_INVALID"):
        await connector.read_document(scope, outside)
