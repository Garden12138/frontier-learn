from uuid import uuid4

from httpx import AsyncClient

from app.api.auth import LoginResponse
from app.domain.planning_types import GoalResponse, PlanResponse


async def authenticate(client: AsyncClient, identity: str = "planner-user") -> dict[str, str]:
    response = await client.post("/api/v1/auth/mock-login", json={"identity": identity})
    session = LoginResponse.model_validate(response.json())
    return {"Authorization": f"Bearer {session.access_token}"}


async def make_goal(
    client: AsyncClient,
    headers: dict[str, str],
    title: str = "理解园艺基础",
    priorities: list[str] | None = None,
    minutes: int = 30,
) -> GoalResponse:
    response = await client.post(
        "/api/v1/goals",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "title": title,
            "minutes_per_day": minutes,
            "priorities": priorities or [],
            "timezone": "Asia/Shanghai",
        },
    )
    assert response.status_code == 201
    return GoalResponse.model_validate(response.json())


async def generate(
    client: AsyncClient, headers: dict[str, str], goal: GoalResponse, revision: int = 0
) -> PlanResponse:
    response = await client.post(
        "/api/v1/plans:generate",
        headers=headers,
        json={
            "goal_id": str(goal.id),
            "goal_version": goal.version,
            "expected_revision_no": revision,
        },
    )
    assert response.status_code == 200, response.text
    return PlanResponse.model_validate(response.json())
