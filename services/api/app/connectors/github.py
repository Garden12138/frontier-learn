import base64
import hashlib
import re
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.connectors.base import DocumentRef, Snapshot, SourceScope
from app.core.errors import Problem
from app.core.security import MAX_BATCH_BYTES, MAX_BATCH_FILES, MAX_INPUT_BYTES
from app.ingestion.http_reader import HTTPReader, PinnedHTTPReader

IGNORED_DIRS = frozenset(
    {".git", ".venv", "node_modules", "dist", "build", "public", "vendor", "__pycache__", ".output"}
)
CODE_SUFFIXES = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".c", ".cpp", ".sh", ".sql"}
)
SHA_PATTERN = r"^[a-f0-9]{40}$"


def repository_ref(value: str) -> str:
    if value.startswith("https://"):
        parsed = urlsplit(value)
        try:
            valid = parsed.hostname == "github.com" and parsed.port in (None, 443)
        except ValueError:
            valid = False
        if not valid or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise Problem(400, "INVALID_REPOSITORY", "请选择 https://github.com 下的单个仓库。")
        value = parsed.path.strip("/")
    value = value.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value):
        raise Problem(400, "INVALID_REPOSITORY", "请输入 owner/repository 或 GitHub 仓库网址。")
    if value.split("/")[1] in {".", ".."}:
        raise Problem(400, "INVALID_REPOSITORY", "仓库路径无效。")
    return value.lower()


def supported_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(
        parts
        and len(path) <= 1000
        and not path.startswith("/")
        and "\\" not in path
        and all(part not in {".", ".."} | IGNORED_DIRS for part in path.split("/"))
        and not any(ord(c) < 32 for c in path)
        and PurePosixPath(path).suffix.lower() in CODE_SUFFIXES | {".md", ".markdown"}
    )


def file_limit(path: str) -> int:
    return 128_000 if PurePosixPath(path).suffix.lower() in CODE_SUFFIXES else MAX_INPUT_BYTES


def normalize_prefixes(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        value = value.strip().rstrip("/")
        if (
            not value
            or len(value) > 512
            or value.startswith("/")
            or "\\" in value
            or any(ord(c) < 32 for c in value)
            or any(p in {"", ".", ".."} for p in value.split("/"))
        ):
            raise ValueError("Folder prefixes must stay within the selected repository")
        if value + "/" not in result:
            result.append(value + "/")
    return result


def within_scope(path: str, scope: SourceScope) -> bool:
    return not scope.path_prefixes or any(path.startswith(prefix) for prefix in scope.path_prefixes)


class TreeEntry(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    type: str
    mode: str
    sha: str = Field(pattern=SHA_PATTERN)
    size: int = Field(default=0, ge=0)


class Tree(BaseModel):
    tree: list[TreeEntry] = Field(max_length=100_000)
    truncated: bool


class CommitTree(BaseModel):
    sha: str = Field(pattern=SHA_PATTERN)


class CommitData(BaseModel):
    tree: CommitTree


class Commit(BaseModel):
    sha: str = Field(pattern=SHA_PATTERN)
    commit: CommitData


class Repository(BaseModel):
    default_branch: str = Field(min_length=1, max_length=255)


class Blob(BaseModel):
    sha: str = Field(pattern=SHA_PATTERN)
    encoding: str
    content: str
    size: int = Field(ge=0, le=MAX_INPUT_BYTES)


class GitHubConnector:
    provider = "github"
    supported_operations = frozenset({"READ_TREE", "READ_DOCUMENT"})

    def __init__(
        self, repository: str, token: SecretStr | None = None, reader: HTTPReader | None = None
    ) -> None:
        self.repository = repository_ref(repository)
        self.token = token
        self.reader = reader or PinnedHTTPReader(frozenset({"api.github.com"}))
        self.request_count = 0
        self.response_bytes = 0

    async def _json[Model: BaseModel](
        self, suffix: str, schema: type[Model], max_bytes: int = 8_000_000
    ) -> Model:
        self.request_count += 1
        if self.request_count > 512:
            raise Problem(429, "CONNECTOR_BUDGET", "本次同步的来源请求已达上限。")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token.get_secret_value()}"
        response = await self.reader.get(
            f"https://api.github.com/repos/{self.repository}{suffix}",
            headers=headers,
            max_bytes=max_bytes,
        )
        self.response_bytes += len(response.body)
        if self.response_bytes > 40_000_000:
            raise Problem(429, "CONNECTOR_BUDGET", "本次同步的网络响应总量超过预算。")
        if response.status in (403, 429) and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in response.headers
            or response.status == 429
        ):
            raise Problem(429, "GITHUB_RATE_LIMIT", "GitHub 请求额度不足，请等待额度恢复后重试。")
        if response.status in (401, 403, 404):
            raise Problem(
                403, "GITHUB_ACCESS_DENIED", "仓库不可访问或授权已失效，请重新授权或选择公开仓库。"
            )
        if response.status == 409:
            raise Problem(400, "EMPTY_REPOSITORY", "仓库尚无提交，请添加笔记后重试。")
        if response.status in (301, 302, 303, 307, 308):
            # Never forward repository credentials through a redirect.
            raise Problem(409, "REPOSITORY_MOVED", "仓库地址已变化，请检查并重新连接。")
        if response.status != 200:
            raise Problem(503, "GITHUB_UNAVAILABLE", "GitHub 暂时不可用，请稍后重试。")
        try:
            return schema.model_validate_json(response.body)
        except (ValidationError, ValueError):
            raise Problem(502, "GITHUB_INVALID_RESPONSE", "来源响应格式不受支持。") from None

    def _check_scope(self, scope: SourceScope) -> None:
        if scope.repository != self.repository:
            raise Problem(403, "SOURCE_SCOPE_DENIED", "请求超出已授权的仓库范围。")

    async def snapshot(self, scope: SourceScope) -> Snapshot:
        self._check_scope(scope)
        repo = await self._json("", Repository, 64_000)
        commit = await self._json(f"/commits/{quote(repo.default_branch, safe='')}", Commit)
        tree_sha = commit.commit.tree.sha
        tree = await self._json(f"/git/trees/{tree_sha}?recursive=1", Tree)
        entries = tree.tree
        if tree.truncated:
            entries = []
            pending = [("", tree_sha)]
            while pending:
                prefix, sha = pending.pop()
                subtree = await self._json(f"/git/trees/{sha}", Tree)
                if subtree.truncated:
                    raise Problem(413, "TREE_INCOMPLETE", "目录树不完整，未删除任何既有证据。")
                for entry in subtree.tree:
                    path = f"{prefix}{entry.path}"
                    if entry.type == "tree":
                        if entry.path not in IGNORED_DIRS:
                            pending.append((f"{path}/", entry.sha))
                    else:
                        entries.append(entry.model_copy(update={"path": path}))
                if len(entries) + len(pending) > 100_000:
                    raise Problem(413, "TREE_LIMIT", "仓库目录规模超过本次同步上限。")
        files = [
            DocumentRef(e.path, e.sha, e.size)
            for e in entries
            if e.type == "blob"
            and e.mode in {"100644", "100755"}
            and supported_path(e.path)
            and within_scope(e.path, scope)
        ]
        if len({f.path for f in files}) != len(files):
            raise Problem(502, "TREE_INVALID", "来源返回重复文件路径。")
        if len(files) > MAX_BATCH_FILES:
            raise Problem(
                413, "BATCH_FILE_LIMIT", "每个来源最多导入 200 份支持的文件，请缩小仓库范围。"
            )
        if sum(f.size for f in files if f.size <= file_limit(f.path)) > MAX_BATCH_BYTES:
            raise Problem(413, "BATCH_BYTE_LIMIT", "可解析文本合计超过 10MB，未改动既有证据。")
        return Snapshot(
            commit.sha, tuple(sorted(files, key=lambda f: f.path)), len(entries) - len(files)
        )

    async def read_document(self, scope: SourceScope, document: DocumentRef) -> bytes:
        self._check_scope(scope)
        if (
            not re.fullmatch(SHA_PATTERN, document.blob_sha)
            or not supported_path(document.path)
            or not within_scope(document.path, scope)
        ):
            raise Problem(400, "DOCUMENT_INVALID", "文件引用无效。")
        if document.size > file_limit(document.path):
            raise Problem(413, "FILE_TOO_LARGE", "文件超过可解析大小上限。")
        blob = await self._json(f"/git/blobs/{document.blob_sha}", Blob, 1_500_000)
        try:
            if blob.encoding != "base64":
                raise ValueError
            content = base64.b64decode("".join(blob.content.splitlines()), validate=True)
        except ValueError:
            raise Problem(502, "BLOB_INVALID", "文件内容编码无效。") from None
        expected = hashlib.sha1(
            f"blob {len(content)}\0".encode() + content, usedforsecurity=False
        ).hexdigest()
        if (
            blob.sha != document.blob_sha
            or expected != document.blob_sha
            or len(content) != blob.size
            or len(content) != document.size
        ):
            raise Problem(502, "BLOB_MISMATCH", "文件版本校验失败，保留已有内容。")
        if len(content) > file_limit(document.path):
            raise Problem(413, "FILE_TOO_LARGE", "文件超过可解析大小上限。")
        return content
