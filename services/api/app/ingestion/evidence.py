import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.ingestion.markdown import ParsedChunk


@dataclass(frozen=True)
class EvidenceCandidate:
    name: str
    canonical_name: str
    chunk_index: int
    kind: str
    method: str = "SOURCE_TEXT"


def canonical_concept(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())[:160]


def extract_candidates(
    path: str, text: str, chunks: list[ParsedChunk], *, code: bool = False
) -> list[EvidenceCandidate]:
    candidates: dict[str, EvidenceCandidate] = {}
    for index, chunk in enumerate(chunks):
        # Verify the locator against the exact decoded document, never a model's claim.
        if (
            text[chunk.start : chunk.end] != chunk.text
            or chunk.line_start < 1
            or chunk.line_end < chunk.line_start
        ):
            raise ValueError("Invalid source locator")
        names = re.findall(r"^#{1,6}\s+(.{1,160})$", chunk.text, re.MULTILINE) if not code else []
        names += re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", chunk.text)
        filename_only = not candidates and index == 0 and not names
        if filename_only:
            names.insert(0, PurePosixPath(path).stem[:160])
        for name in names:
            name = re.sub(r"[`*_#]", "", name).strip()
            canonical = canonical_concept(name)
            if canonical and canonical not in candidates and len(candidates) < 32:
                candidates[canonical] = EvidenceCandidate(
                    name,
                    canonical,
                    index,
                    "CODE_ARTIFACT" if code or chunk.content_type == "CODE" else "OBSERVED_NOTE",
                    "FILE_TITLE" if filename_only else "SOURCE_TEXT",
                )
    return list(candidates.values())
