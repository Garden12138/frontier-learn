import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

import httpcore

from app.core.errors import Problem
from app.core.security import Resolver, SafeTarget, resolve_addresses, validate_destination


@dataclass(frozen=True)
class ReadResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class HTTPReader(Protocol):
    async def get(self, url: str, *, headers: dict[str, str], max_bytes: int) -> ReadResponse: ...


class PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self, target: SafeTarget, backend: httpcore.AsyncNetworkBackend | None = None
    ) -> None:
        self.target = target
        self.backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore interface
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if host != self.target.hostname or port != 443:
            raise Problem(400, "UNSAFE_URL", "网络目标与已授权来源不一致。")
        # TLS still uses the original origin hostname in httpcore. Only TCP uses this literal IP.
        addresses = sorted(self.target.addresses, key=lambda address: ":" in address)[:2]
        for index, address in enumerate(addresses):
            try:
                return await self.backend.connect_tcp(
                    address, port, min(timeout or 5, 2.5), local_address, socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout):
                if index == len(addresses) - 1:
                    raise
        raise httpcore.ConnectError("No validated destination available")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class PinnedHTTPReader:
    def __init__(
        self,
        allowed_hosts: frozenset[str],
        *,
        resolver: Resolver = resolve_addresses,
        backend_factory: Callable[[SafeTarget], httpcore.AsyncNetworkBackend] = PinnedBackend,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.resolver = resolver
        self.backend_factory = backend_factory

    async def get(self, url: str, *, headers: dict[str, str], max_bytes: int) -> ReadResponse:
        return await self.request("GET", url, headers=headers, max_bytes=max_bytes)

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        max_bytes: int,
        content: bytes = b"",
    ) -> ReadResponse:
        if method not in {"GET", "POST", "PUT"} or len(content) > 200_000:
            raise Problem(400, "FETCH_LIMIT", "网络请求超出允许范围。")
        target = await validate_destination(
            url, allowed_hosts=self.allowed_hosts, resolver=self.resolver
        )
        if not 1 <= max_bytes <= 8_000_000:
            raise Problem(400, "FETCH_LIMIT", "网络响应预算无效。")
        try:
            async with asyncio.timeout(15):
                async with httpcore.AsyncConnectionPool(
                    network_backend=self.backend_factory(target),
                    max_connections=1,
                    max_keepalive_connections=0,
                    retries=0,
                ) as pool:
                    async with pool.stream(
                        method,
                        target.url,
                        content=content,
                        headers=[
                            (key.encode("ascii"), value.encode("ascii"))
                            for key, value in {
                                **headers,
                                "Accept-Encoding": "identity",
                                "User-Agent": "FrontierLearn/0.1",
                            }.items()
                        ],
                        extensions={"timeout": {"connect": 5, "read": 10, "write": 5, "pool": 5}},
                    ) as response:
                        result_headers = {
                            k.decode().lower(): v.decode("latin1") for k, v in response.headers
                        }
                        if result_headers.get("content-encoding", "identity") != "identity":
                            raise Problem(502, "ENCODING_UNSUPPORTED", "来源返回不支持的压缩内容。")
                        body = bytearray()
                        async for chunk in response.aiter_stream():
                            if len(body) + len(chunk) > max_bytes:
                                raise Problem(413, "RESPONSE_TOO_LARGE", "来源响应超过大小限制。")
                            body.extend(chunk)
                        return ReadResponse(response.status, result_headers, bytes(body))
        except (
            httpcore.NetworkError,
            httpcore.ProtocolError,
            httpcore.TimeoutException,
            TimeoutError,
            OSError,
        ):
            raise Problem(503, "SOURCE_UNAVAILABLE", "暂时无法访问来源，请稍后重试。") from None
