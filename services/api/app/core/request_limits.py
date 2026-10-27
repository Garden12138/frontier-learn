import asyncio

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.security import MAX_INPUT_BYTES


class RequestLimits:
    """Bound total API request bytes, including chunked requests without Content-Length."""

    def __init__(self, app: ASGIApp, limit: int = MAX_INPUT_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def reject(status: int, code: str, message: str) -> None:
            await JSONResponse(
                status_code=status,
                content={
                    "code": code,
                    "message": message,
                    "request_id": scope.get("state", {}).get("request_id", ""),
                },
            )(scope, receive, send)

        headers = dict(scope.get("headers", []))
        try:
            declared_length = int(headers.get(b"content-length", b"0"))
            if declared_length < 0:
                raise ValueError
        except ValueError:
            await reject(400, "INVALID_REQUEST", "请求长度无效。")
            return
        if declared_length > self.limit:
            await reject(413, "REQUEST_TOO_LARGE", "请求内容过大，请缩小内容范围。")
            return
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self.limit:
                        await reject(413, "REQUEST_TOO_LARGE", "请求内容过大，请缩小内容范围。")
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408, "REQUEST_TIMEOUT", "读取请求超时，请重试。")
            return
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
