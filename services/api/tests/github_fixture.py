import base64
import hashlib
import json
from urllib.parse import urlsplit

from app.ingestion.http_reader import ReadResponse


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(content)}\0".encode() + content, usedforsecurity=False
    ).hexdigest()


class GitHubFixture:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.revision = "a" * 40
        self.calls: list[str] = []
        self.status = 200
        self.blob_failures: set[str] = set()
        self.truncated = False

    async def get(self, url: str, *, headers: dict[str, str], max_bytes: int) -> ReadResponse:
        self.calls.append(url)
        path = urlsplit(url).path
        if self.status != 200:
            return ReadResponse(
                self.status,
                {"x-ratelimit-remaining": "0"} if self.status == 429 else {},
                b"PRIVATE_ERROR_BODY",
            )
        if path.endswith("/git/trees/" + "b" * 40):
            body: dict[str, object] = {
                "tree": [
                    {
                        "path": p,
                        "sha": blob_sha(c),
                        "type": "blob",
                        "mode": "100644",
                        "size": len(c),
                    }
                    for p, c in self.files.items()
                ],
                "truncated": self.truncated and bool(urlsplit(url).query),
            }
        elif "/git/blobs/" in path:
            sha = path.rsplit("/", 1)[-1]
            if sha in self.blob_failures:
                return ReadResponse(503, {}, b"PRIVATE_ERROR_BODY")
            content = next(c for c in self.files.values() if blob_sha(c) == sha)
            body = {
                "sha": sha,
                "size": len(content),
                "encoding": "base64",
                "content": base64.b64encode(content).decode(),
            }
        elif "/commits/" in path:
            body = {"sha": self.revision, "commit": {"tree": {"sha": "b" * 40}}}
        else:
            body = {"default_branch": "main"}
        encoded = json.dumps(body).encode()
        assert len(encoded) <= max_bytes
        return ReadResponse(200, {}, encoded)
