"""Public share fetcher: no cookies, script execution, private API or arbitrary URL."""

import asyncio
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import UUID

from app.core.errors import Problem
from app.ingestion.http_reader import HTTPReader, PinnedHTTPReader

SHARE_HOSTS = frozenset({"chatgpt.com", "chat.openai.com"})
MAX_SHARE_BYTES = 1_000_000


def share_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        match = re.fullmatch(r"/share/([0-9a-fA-F-]{36})/?", parsed.path)
        if (
            len(value) > 2048
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            or "\\" in value
            or parsed.scheme != "https"
            or parsed.hostname not in SHARE_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or not match
        ):
            raise ValueError
        identifier = str(UUID(match[1]))
        return urlunsplit(("https", parsed.hostname, f"/share/{identifier}", "", ""))
    except ValueError:
        raise Problem(
            400, "UNSUPPORTED_SHARE_URL", "请使用公开 ChatGPT 分享链接，或改用手工粘贴。"
        ) from None


class ShareFetcher:
    def __init__(self, reader: HTTPReader | None = None) -> None:
        self.reader = reader or PinnedHTTPReader(SHARE_HOSTS)

    async def fetch(self, value: str) -> str:
        url = share_url(value)
        identifier = urlsplit(url).path
        remaining = MAX_SHARE_BYTES
        try:
            async with asyncio.timeout(20):
                for hop in range(3):
                    response = await self.reader.get(
                        url,
                        headers={"Accept": "text/html"},
                        max_bytes=remaining,
                    )
                    remaining -= len(response.body)
                    if remaining < 0:
                        raise Problem(
                            413, "RESPONSE_TOO_LARGE", "分享页超过导入大小限制，请粘贴必要片段。"
                        )
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location", "")
                        if (
                            any(ord(char) <= 32 or ord(char) == 127 for char in location)
                            or "\\" in location
                        ):
                            raise Problem(
                                400, "SHARE_REDIRECT_DENIED", "分享页跳转目标不合法，请手工粘贴。"
                            )
                        if not location or hop == 2 or remaining == 0:
                            raise Problem(
                                400, "SHARE_REDIRECT_LIMIT", "分享页跳转超出边界，请改用粘贴。"
                            )
                        next_url = share_url(urljoin(url, location))
                        if urlsplit(next_url).path != identifier:
                            raise Problem(
                                400, "SHARE_REDIRECT_DENIED", "跳转到了其他材料，请核对链接。"
                            )
                        url = next_url
                        continue
                    if response.status in {401, 403}:
                        raise Problem(
                            403,
                            "SHARE_ACCESS_DENIED",
                            "分享页限制访问；不会绕过，请粘贴你能访问的内容。",
                        )
                    if response.status in {404, 410}:
                        raise Problem(
                            404, "SHARE_NOT_AVAILABLE", "分享页已失效或不存在，请改用手工粘贴。"
                        )
                    if response.status == 429:
                        raise Problem(
                            503, "SHARE_RATE_LIMITED", "分享页暂时限流，可稍后重试或粘贴。"
                        )
                    if response.status != 200:
                        raise Problem(
                            503, "SHARE_UNAVAILABLE", "暂时无法获取分享页，请重试或粘贴。"
                        )
                    content_type = (
                        response.headers.get("content-type", "").split(";")[0].strip().lower()
                    )
                    if (
                        content_type != "text/html"
                        or response.headers.get("content-encoding", "identity") != "identity"
                    ):
                        raise Problem(
                            400, "SHARE_FORMAT_UNSUPPORTED", "分享页内容格式不支持，请手工粘贴。"
                        )
                    try:
                        return response.body.decode("utf-8", errors="strict")
                    except UnicodeDecodeError:
                        raise Problem(
                            400, "SHARE_ENCODING", "分享页编码无法解析，请手工粘贴。"
                        ) from None
        except TimeoutError:
            raise Problem(503, "SHARE_TIMEOUT", "分享页获取超时，请重试或手工粘贴。") from None
        raise Problem(400, "SHARE_REDIRECT_LIMIT", "分享页跳转超出边界。")
