import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

import app.database
import app.main
import app.webhook_registry
from app.dependencies import get_current_user, get_redis
from app.metrics import CUSTOMER_WEBHOOK_TOTAL
from app.models.customer import Customer
from app.models.webhook_event import WebhookEvent

_ERRORS_METRIC = "customer_webhook_errors_total"

# 테넌트별 DB 시크릿(customer.webhook_secret) 방식을 그대로 사용 — 실 서명 검증용 시크릿
TEST_SECRET = "test-webhook-secret-0123456789abcdef"  # noqa: S105 (테스트 전용 더미)


def _counter_value(counter, **labels):
    """Read current value of a Counter for specific labels."""
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == labels:
                return sample.value
    return 0.0


def _github_signature(body: bytes, secret: str = TEST_SECRET) -> str:
    """실제 GitHub HMAC-SHA256 서명 생성 (X-Hub-Signature-256)."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _stripe_signature(body: bytes, secret: str = TEST_SECRET, timestamp: int | None = None) -> str:
    """실제 Stripe 서명 헤더 생성 (t=...,v1=HMAC-SHA256(`{t}.{payload}`))."""
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.".encode() + body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


class _FakeAsyncDB:
    """get_async_db 대체 — verify 경로가 실제로 실행되도록 customer만 주입.

    verify_github/verify_stripe를 mock하지 않는다. CustomerRepository가
    `await db.execute(select(...)).scalar_one_or_none()`로 customer를 조회하므로
    그 결과만 흉내 낸다(테넌트 상태는 customer 속성으로 제어).
    """

    def __init__(self):
        self.customer = None

    async def execute(self, *args, **kwargs):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.customer
        return result


@pytest.fixture
def db_session_mock():
    return MagicMock()


@pytest.fixture
def redis_mock():
    mock = MagicMock()
    mock.set = AsyncMock(return_value=True)  # 기본: 성공 (중복 없음)
    return mock


@pytest.fixture
def active_customer():
    customer = MagicMock(spec=Customer)
    customer.id = "mock_customer_id"
    customer.is_active = True
    customer.webhook_secret = TEST_SECRET
    return customer


@pytest.fixture
def async_db(active_customer):
    db = _FakeAsyncDB()
    db.customer = active_customer
    return db


@pytest.fixture
def client(mocker, db_session_mock, redis_mock, async_db):
    app.main.app.dependency_overrides[get_redis] = lambda: redis_mock
    app.main.app.dependency_overrides[app.database.get_db] = lambda: db_session_mock
    app.main.app.dependency_overrides[app.database.get_async_db] = lambda: async_db

    mock_task = MagicMock()
    mocker.patch("app.main.get_task", return_value=mock_task)

    mock_user_info = {
        "preferred_username": "testuser",
        "realm_access": {"roles": ["admin", "user"]},
    }
    app.main.app.dependency_overrides[get_current_user] = lambda: mock_user_info

    test_client = TestClient(app.main.app)
    yield test_client, mock_task

    app.main.app.dependency_overrides.clear()


def _post_github(test_client, tenant_id, payload, *, secret=TEST_SECRET, delivery="d-1"):
    """유효 GitHub 서명을 붙여 전송 — 보낸 바이트 그대로 서명한다."""
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "X-Hub-Signature-256": _github_signature(body, secret),
        "X-GitHub-Delivery": delivery,
    }
    return test_client.post(f"/webhooks/{tenant_id}/github", content=body, headers=headers)


def _post_stripe(test_client, tenant_id, payload, *, secret=TEST_SECRET):
    """유효 Stripe 서명을 붙여 전송 — 보낸 바이트 그대로 서명한다."""
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "stripe-signature": _stripe_signature(body, secret),
    }
    return test_client.post(f"/webhooks/{tenant_id}/stripe", content=body, headers=headers)


def test_security_headers_present(client):
    """모든 응답에 보안 헤더가 설정되는지 검증 (clickjacking·MIME 스니핑 방어)."""
    test_client, _ = client
    # HTTP: HSTS 제외, 나머지 보안 헤더 존재 (RFC 6797 §7.2)
    res_http = test_client.get("/")
    assert res_http.headers["X-Content-Type-Options"] == "nosniff"
    assert res_http.headers["X-Frame-Options"] == "DENY"
    assert res_http.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Strict-Transport-Security" not in res_http.headers
    # HTTPS(프록시 X-Forwarded-Proto): 대소문자·멀티 프록시(쉼표) 케이스 포함
    for proto in ["https", "HTTPS", "https, http"]:
        res_https = test_client.get("/", headers={"X-Forwarded-Proto": proto})
        assert "max-age=" in res_https.headers["Strict-Transport-Security"]


# ─── GitHub 실 HMAC 서명 검증 ────────────────────────────────────────────────


def test_receive_github_webhook_valid_signature(client):
    """유효한 GitHub HMAC-SHA256 서명 → 202, 큐잉 (실제 _verify_github 실행)."""
    test_client, mock_task = client
    tenant_id = "some-tenant"
    payload = {"action": "opened"}

    initial_webhook_total = _counter_value(
        CUSTOMER_WEBHOOK_TOTAL, customer_id="mock_customer_id", source="github"
    )

    response = _post_github(test_client, tenant_id, payload)

    assert response.status_code == 202
    assert response.json() == {"message": "Webhook received and queued for processing."}
    mock_task.apply_async.assert_called_once()
    assert (
        _counter_value(CUSTOMER_WEBHOOK_TOTAL, customer_id="mock_customer_id", source="github")
        == initial_webhook_total + 1
    )


def test_receive_github_webhook_invalid_signature(client):
    """위조된 서명 값 → 401 (실제 hmac.compare_digest 불일치)."""
    test_client, mock_task = client
    tenant_id = "some-tenant"
    body = json.dumps({"action": "opened"}).encode("utf-8")

    error_labels = {
        "customer_id": tenant_id,
        "source": "github",
        "error_type": "Invalid GitHub signature.",
    }
    initial_error_total = REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) or 0

    response = test_client.post(
        f"/webhooks/{tenant_id}/github",
        content=body,
        headers={
            "content-type": "application/json",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "X-GitHub-Delivery": "d-bad",
        },
    )

    assert response.status_code == 401
    mock_task.apply_async.assert_not_called()
    assert REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) == initial_error_total + 1


def test_receive_github_webhook_tampered_body(client):
    """유효 서명을 만든 뒤 body를 변조 → 401 (서명은 원본 바이트에만 유효)."""
    test_client, mock_task = client
    tenant_id = "some-tenant"

    original_body = json.dumps({"action": "opened"}).encode("utf-8")
    signature = _github_signature(original_body)
    tampered_body = json.dumps({"action": "deleted"}).encode("utf-8")

    response = test_client.post(
        f"/webhooks/{tenant_id}/github",
        content=tampered_body,
        headers={
            "content-type": "application/json",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "d-tampered",
        },
    )

    assert response.status_code == 401
    mock_task.apply_async.assert_not_called()


def test_receive_github_webhook_missing_signature(client):
    """X-Hub-Signature-256 헤더 부재 → 400."""
    test_client, mock_task = client
    body = json.dumps({"action": "opened"}).encode("utf-8")

    response = test_client.post(
        "/webhooks/some-tenant/github",
        content=body,
        headers={"content-type": "application/json", "X-GitHub-Delivery": "d-nosig"},
    )

    assert response.status_code == 400
    mock_task.apply_async.assert_not_called()


def test_receive_webhook_tenant_not_found(client, async_db):
    """존재하지 않는 테넌트 → 404 (실제 _get_customer_async 경로)."""
    test_client, _ = client
    tenant_id = "non-existent-tenant"
    async_db.customer = None

    error_labels = {
        "customer_id": tenant_id,
        "source": "github",
        "error_type": "Tenant not found.",
    }
    initial_error_total = REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) or 0

    response = _post_github(test_client, tenant_id, {"action": "opened"})

    assert response.status_code == 404
    assert REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) == initial_error_total + 1


def test_receive_webhook_inactive_tenant(client, async_db, active_customer):
    """비활성 테넌트 → 403 (실제 _get_customer_async 정책 분기)."""
    test_client, _ = client
    tenant_id = "inactive-tenant"
    active_customer.is_active = False
    async_db.customer = active_customer

    error_labels = {
        "customer_id": tenant_id,
        "source": "github",
        "error_type": "Tenant is inactive.",
    }
    initial_error_total = REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) or 0

    response = _post_github(test_client, tenant_id, {"action": "ping"})

    assert response.status_code == 403
    assert REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) == initial_error_total + 1


# ─── Stripe 실 서명 검증 (construct_event, 300s 허용오차 유지) ────────────────


def test_receive_stripe_webhook_valid_signature(client):
    """유효한 Stripe 서명 → 202 (실제 construct_event 실행)."""
    test_client, mock_task = client
    tenant_id = "some-tenant"
    payload = {"id": "evt_test_1", "type": "customer.created"}

    initial_webhook_total = _counter_value(
        CUSTOMER_WEBHOOK_TOTAL, customer_id="mock_customer_id", source="stripe"
    )

    response = _post_stripe(test_client, tenant_id, payload)

    assert response.status_code == 202
    assert response.json() == {"message": "Webhook received and queued for processing."}
    mock_task.apply_async.assert_called_once()
    assert (
        _counter_value(CUSTOMER_WEBHOOK_TOTAL, customer_id="mock_customer_id", source="stripe")
        == initial_webhook_total + 1
    )


def test_receive_stripe_webhook_invalid_signature(client):
    """위조된 Stripe 서명 → 401 (SignatureVerificationError)."""
    test_client, mock_task = client
    tenant_id = "some-tenant"
    body = json.dumps({"id": "evt_bad", "type": "customer.created"}).encode("utf-8")

    error_labels = {
        "customer_id": tenant_id,
        "source": "stripe",
        "error_type": "Invalid Stripe signature.",
    }
    initial_error_total = REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) or 0

    response = test_client.post(
        f"/webhooks/{tenant_id}/stripe",
        content=body,
        headers={
            "content-type": "application/json",
            "stripe-signature": f"t={int(time.time())},v1={'0' * 64}",
        },
    )

    assert response.status_code == 401
    mock_task.apply_async.assert_not_called()
    assert REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) == initial_error_total + 1


def test_receive_stripe_webhook_missing_signature(client):
    """Stripe-Signature 헤더 부재 → 400."""
    test_client, mock_task = client
    body = json.dumps({"id": "evt_x", "type": "customer.created"}).encode("utf-8")

    response = test_client.post(
        "/webhooks/some-tenant/stripe",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    mock_task.apply_async.assert_not_called()


# ─── 멱등성 (실 서명을 붙여 verify 통과 후 Redis NX 분기 검증) ─────────────────


def test_github_webhook_idempotent_duplicate(client, redis_mock):
    """동일 X-GitHub-Delivery ID로 두 번 요청 시 두 번째는 큐잉 없이 202 반환."""
    test_client, mock_task = client
    tenant_id = "some-tenant"

    # 두 번째 요청: Redis에 이미 처리된 키 존재 (set nx=True가 False 반환)
    redis_mock.set.return_value = False

    response = _post_github(
        test_client, tenant_id, {"action": "opened"}, delivery="abc-123-delivery"
    )

    assert response.status_code == 202
    mock_task.apply_async.assert_not_called()


def test_stripe_webhook_idempotent_duplicate(client, redis_mock):
    """동일 Stripe event ID로 두 번 요청 시 두 번째는 큐잉 없이 202 반환."""
    test_client, mock_task = client
    tenant_id = "some-tenant"

    # 두 번째 요청: Redis에 이미 처리된 키 존재 (set nx=True가 False 반환)
    redis_mock.set.return_value = False

    response = _post_stripe(
        test_client,
        tenant_id,
        {"id": "evt_duplicate_123", "type": "payment_intent.succeeded"},
    )

    assert response.status_code == 202
    mock_task.apply_async.assert_not_called()


# ─── Replay (Keycloak 인증 + 테넌트 격리, 동기 경로) ──────────────────────────


def test_replay_event_success(client, db_session_mock, mocker):
    """Tests successful re-queuing of an event with authentication and tenant_id."""
    test_client, mock_task = client
    tenant_id = "some-tenant"
    event_id = 1
    mock_customer_id = "mock_customer_id"
    mock_payload = {"key": "value"}

    mock_customer = MagicMock(spec=Customer)
    mock_customer.id = mock_customer_id
    mock_customer.is_active = True
    mocker.patch("app.main.WebhookVerifier._get_customer", return_value=mock_customer)

    mock_event = MagicMock(spec=WebhookEvent)
    mock_event.id = event_id
    mock_event.customer_id = mock_customer_id
    mock_event.source = "github"
    mock_event.payload = mock_payload
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = mock_event
    db_session_mock.execute.return_value = exec_result

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 202
    assert response.json() == {"message": f"Event {event_id} has been re-queued for processing."}
    mock_task.delay.assert_called_once_with(mock_customer_id, mock_payload)


def test_replay_event_unauthorized(client):
    """Tests that replaying an event without authentication returns 401."""
    test_client, _ = client
    tenant_id = "some-tenant"
    event_id = 1

    # Remove auth override so the real get_current_user runs (no auth header → 401)
    app.main.app.dependency_overrides.pop(get_current_user, None)

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 401
    assert "Authorization header missing" in response.text


def test_replay_event_forbidden(client):
    """Tests that replaying an event with insufficient permissions returns 403."""
    test_client, _ = client
    tenant_id = "some-tenant"
    event_id = 1

    app.main.app.dependency_overrides[get_current_user] = lambda: {
        "preferred_username": "testuser",
        "realm_access": {"roles": ["user"]},
    }

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 403
    assert "Not enough permissions" in response.text


def test_replay_event_tenant_not_found(client, mocker):
    """Tests that replaying an event for a non-existent tenant returns 404."""
    test_client, _ = client
    tenant_id = "non-existent-tenant"
    event_id = 1

    mocker.patch("app.main.WebhookVerifier._get_customer", return_value=None)

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 404
    assert "Tenant not found or inactive." in response.text


def test_replay_event_event_not_found_for_tenant(client, db_session_mock, mocker):
    """Tests that replaying a non-existent event for a given tenant returns 404."""
    test_client, _ = client
    tenant_id = "some-tenant"
    event_id = 999
    mock_customer_id = "mock_customer_id"

    mock_customer = MagicMock(spec=Customer)
    mock_customer.id = mock_customer_id
    mock_customer.is_active = True
    mocker.patch("app.main.WebhookVerifier._get_customer", return_value=mock_customer)
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db_session_mock.execute.return_value = exec_result

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 404
    assert "Event not found for this tenant" in response.text


def test_replay_event_data_isolation(client, db_session_mock, mocker):
    """Tests that events from other tenants return 404 (data isolation)."""
    test_client, _ = client
    tenant_id = "tenant-a"
    event_id = 1
    mock_customer_id_a = "customer_id_a"

    mock_customer_a = MagicMock(spec=Customer)
    mock_customer_a.id = mock_customer_id_a
    mock_customer_a.is_active = True
    mocker.patch("app.main.WebhookVerifier._get_customer", return_value=mock_customer_a)

    # Event belongs to a different customer — returns None (data isolation)
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    db_session_mock.execute.return_value = exec_result

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 404
    assert "Event not found for this tenant" in response.text
