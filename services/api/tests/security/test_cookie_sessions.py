import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.postgres


async def test_web_cookie_is_http_only_and_mutations_require_origin(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/mock-login", json={"identity": "cookie-user", "client": "web"}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    source_body = {"external_ref": "sample/notes", "consent": True}
    assert (await client.post("/api/v1/sources", json=source_body)).status_code == 403
    assert (
        await client.post(
            "/api/v1/sources", json=source_body, headers={"Origin": "https://evil.com"}
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/sources", json=source_body, headers={"Origin": "http://localhost:5173"}
        )
    ).status_code == 201
    logout = await client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:5173"})
    assert logout.status_code == 204
    assert (await client.get("/api/v1/auth/me")).status_code == 401
