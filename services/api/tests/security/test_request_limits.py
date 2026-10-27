from collections.abc import AsyncIterator

from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


async def test_chunked_body_is_bounded_before_parsing() -> None:
    app = create_app(Settings(env="test"))

    async def oversized() -> AsyncIterator[bytes]:
        yield b"PRIVATE_BODY" + b"x" * 600_000
        yield b"x" * 600_000

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/auth/mock-login", content=oversized())
    assert response.status_code == 413
    assert response.json()["code"] == "REQUEST_TOO_LARGE"
    assert response.json()["request_id"]
    assert "PRIVATE_BODY" not in response.text


async def test_declared_body_limit_cannot_be_bypassed() -> None:
    app = create_app(Settings(env="test"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/auth/mock-login", content=b"{}", headers={"Content-Length": "1000001"}
            )
    assert response.status_code == 413
