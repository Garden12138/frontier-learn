from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SourceScope:
    repository: str
    path_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentRef:
    path: str
    blob_sha: str
    size: int


@dataclass(frozen=True)
class Snapshot:
    revision: str
    documents: tuple[DocumentRef, ...]
    ignored_count: int = 0


class KnowledgeConnector(Protocol):
    provider: str
    supported_operations: frozenset[str]

    async def snapshot(self, scope: SourceScope) -> Snapshot: ...

    async def read_document(self, scope: SourceScope, document: DocumentRef) -> bytes: ...
