import ssl
from collections.abc import Iterable

import httpcore
import pytest

from app.core.errors import Problem
from app.core.security import SafeTarget
from app.ingestion.http_reader import PinnedBackend, PinnedHTTPReader


class RecordingStream(httpcore.AsyncMockStream):
    def __init__(self, response: bytes) -> None:
        super().__init__([response])
        self.tls_hostname: str | None = None
        self.sent = bytearray()

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore interface
    ) -> httpcore.AsyncNetworkStream:  # noqa: ASYNC109
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        self.tls_hostname = server_hostname
        return self

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:  # noqa: ASYNC109
        self.sent.extend(buffer)


class RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, response: bytes) -> None:
        self.hosts: list[str] = []
        self.stream = RecordingStream(response)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore interface
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:  # noqa: ASYNC109
        self.hosts.append(host)
        return self.stream


async def test_tcp_is_pinned_while_tls_and_host_keep_original_origin() -> None:
    backend = RecordingBackend(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
    resolutions = 0

    async def resolver(hostname: str) -> list[str]:
        nonlocal resolutions
        resolutions += 1
        return ["93.184.216.34"] if resolutions == 1 else ["127.0.0.1"]

    def factory(target: SafeTarget) -> PinnedBackend:
        return PinnedBackend(target, backend)

    reader = PinnedHTTPReader(
        frozenset({"api.github.com"}), resolver=resolver, backend_factory=factory
    )
    response = await reader.get(
        "https://api.github.com/repos/learner/notes", headers={}, max_bytes=100
    )
    assert response.body == b"hello"
    assert resolutions == 1 and backend.hosts == ["93.184.216.34"]
    assert backend.stream.tls_hostname == "api.github.com"
    assert b"Host: api.github.com" in backend.stream.sent
    with pytest.raises(Problem, match="UNSAFE_URL"):
        await reader.get("https://api.github.com/redirect", headers={}, max_bytes=100)
    assert len(backend.hosts) == 1


@pytest.mark.parametrize(
    "response,code",
    [
        (b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello", "RESPONSE_TOO_LARGE"),
        (
            b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 0\r\n\r\n",
            "ENCODING_UNSUPPORTED",
        ),
    ],
)
async def test_remote_bodies_are_bounded(response: bytes, code: str) -> None:
    async def resolver(hostname: str) -> list[str]:
        return ["93.184.216.34"]

    reader = PinnedHTTPReader(
        frozenset({"api.github.com"}),
        resolver=resolver,
        backend_factory=lambda target: PinnedBackend(target, RecordingBackend(response)),
    )
    with pytest.raises(Problem) as error:
        await reader.get("https://api.github.com/", headers={}, max_bytes=2)
    assert error.value.code == code


async def test_post_body_uses_pinned_tls_connection_without_redirecting_credentials() -> None:
    backend = RecordingBackend(b"HTTP/1.1 201 Created\r\nContent-Length: 2\r\n\r\n{}")

    async def resolver(hostname: str) -> list[str]:
        return ["93.184.216.34"]

    reader = PinnedHTTPReader(
        frozenset({"api.github.com"}),
        resolver=resolver,
        backend_factory=lambda target: PinnedBackend(target, backend),
    )
    response = await reader.request(
        "POST",
        "https://api.github.com/repos/sample/notes/git/refs",
        headers={"Content-Type": "application/json"},
        max_bytes=100,
        content=b'{"ref":"refs/heads/frontierlearn/test","sha":"synthetic"}',
    )
    assert response.status == 201
    assert backend.hosts == ["93.184.216.34"]
    assert backend.stream.tls_hostname == "api.github.com"
    assert b"POST /repos/sample/notes/git/refs HTTP/1.1" in backend.stream.sent
    assert b"refs/heads/frontierlearn/test" in backend.stream.sent
