"""공통 에러 Envelope + admin 하드삭제 금지 (PR-4 / M4, M7).

- 전역 예외 핸들러가 모든 에러를 {success, data, error}로 매핑
- 입력 검증 오류는 4xx(422) 유지 (5xx 흡수 금지)
- admin에서 웹훅 이벤트 하드삭제 금지(감사이력 보존)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import app.database
import app.main
from app.admin import WebhookEventAdmin, authentication_backend
from app.dependencies import get_redis


@pytest.fixture
def client():
    app.main.app.dependency_overrides[app.database.get_async_db] = lambda: AsyncMock()
    app.main.app.dependency_overrides[app.database.get_db] = lambda: MagicMock()
    app.main.app.dependency_overrides[get_redis] = lambda: AsyncMock()
    yield TestClient(app.main.app, raise_server_exceptions=False)
    app.main.app.dependency_overrides.clear()


def test_admin_hard_delete_disabled():
    """관리자 UI에서 웹훅 이벤트 하드삭제 금지 (감사이력 보존, M4)."""
    assert WebhookEventAdmin.can_delete is False


def test_admin_ajax_lookup_requires_login(client):
    response = client.get(
        "/admin/webhook-event/ajax/lookup?name=customer&term=x", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith("/admin/login")


def test_admin_sorting_rejects_hidden_column(isolated_service_db, client, mocker):
    mocker.patch.object(
        authentication_backend, "authenticate", new_callable=AsyncMock, return_value=True
    )
    allowed = client.get("/admin/webhook-event/list?sortBy=id")
    hidden = client.get("/admin/webhook-event/list?sortBy=payload")
    assert allowed.status_code == 200
    assert hidden.status_code == 400


def test_metrics_endpoint_remains_available(client):
    client.get("/")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


def test_http_exception_uses_common_envelope(client):
    """HTTPException(401)이 공통 Envelope로 매핑된다 (헤더 보존)."""
    res = client.post("/webhooks/some-tenant/events/1/replay")  # 인증 없음 → 401
    assert res.status_code == 401
    body = res.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == 401
    assert "Authorization header missing" in body["error"]["message"]


def test_validation_error_envelope_keeps_4xx(client):
    """입력 검증 오류는 4xx(422)로 유지 + 공통 Envelope."""
    res = client.post(
        "/webhooks/some-tenant/github",
        content="not-json",
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 422  # 5xx로 흡수되지 않음
    body = res.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == 422
    assert "details" in body["error"]
