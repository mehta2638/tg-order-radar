import httpx

from app.core.correlation import CORRELATION_ID_HEADER
from app.main import create_app


async def test_liveness_endpoint_returns_ok() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers[CORRELATION_ID_HEADER]


async def test_readiness_endpoint_returns_ok_with_existing_correlation_id() -> None:
    transport = httpx.ASGITransport(app=create_app())
    correlation_id = "test-correlation-id"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health/ready", headers={CORRELATION_ID_HEADER: correlation_id}
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers[CORRELATION_ID_HEADER] == correlation_id
