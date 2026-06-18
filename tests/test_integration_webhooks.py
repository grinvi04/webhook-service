from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
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


def _counter_value(counter, **labels):
    """Read current value of a Counter for specific labels."""
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == labels:
                return sample.value
    return 0.0


@pytest.fixture
def db_session_mock():
    return MagicMock()


@pytest.fixture
def redis_mock():
    mock = MagicMock()
    mock.set = AsyncMock(return_value=True)  # 기본: 성공 (중복 없음)
    return mock


@pytest.fixture
def client(mocker, db_session_mock, redis_mock):
    app.main.app.dependency_overrides[get_redis] = lambda: redis_mock
    app.main.app.dependency_overrides[app.database.get_db] = lambda: db_session_mock
    app.main.app.dependency_overrides[app.database.get_async_db] = lambda: (
        db_session_mock
    )

    mock_task = MagicMock()
    mocker.patch("app.main.get_task", return_value=mock_task)

    mock_customer = MagicMock(spec=Customer)
    mock_customer.id = "mock_customer_id"
    mock_customer.is_active = True
    mock_verify_github = mocker.patch(
        "app.main.verify_github", new_callable=AsyncMock, return_value=mock_customer
    )
    mock_verify_stripe = mocker.patch(
        "app.main.verify_stripe", new_callable=AsyncMock, return_value=mock_customer
    )

    mock_user_info = {
        "preferred_username": "testuser",
        "realm_access": {"roles": ["admin", "user"]},
    }
    app.main.app.dependency_overrides[get_current_user] = lambda: mock_user_info

    test_client = TestClient(app.main.app)
    yield test_client, mock_task, mock_verify_github, mock_verify_stripe

    app.main.app.dependency_overrides.clear()


def test_security_headers_present(client):
    """모든 응답에 보안 헤더가 설정되는지 검증 (clickjacking·MIME 스니핑 방어)."""
    test_client, _, _, _ = client
    response = test_client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "max-age=" in response.headers["Strict-Transport-Security"]


def test_receive_github_webhook_success(client):
    """Tests successful reception and queuing of a GitHub webhook for a tenant."""
    test_client, mock_task, _, _ = client
    tenant_id = "some-tenant"
    payload = {"action": "opened"}

    initial_webhook_total = _counter_value(
        CUSTOMER_WEBHOOK_TOTAL, customer_id="mock_customer_id", source="github"
    )

    response = test_client.post(f"/webhooks/{tenant_id}/github", json=payload)

    assert response.status_code == 202
    assert response.json() == {"message": "Webhook received and queued for processing."}
    assert (
        _counter_value(
            CUSTOMER_WEBHOOK_TOTAL, customer_id="mock_customer_id", source="github"
        )
        == initial_webhook_total + 1
    )


def test_receive_github_webhook_invalid_signature(client):
    """Tests that a request with an invalid signature is rejected with 401."""
    test_client, mock_task, mock_verify_github, _ = client
    tenant_id = "some-tenant"
    payload = {"action": "opened"}

    mock_verify_github.side_effect = HTTPException(
        status_code=401, detail="Invalid signature"
    )

    error_labels = {
        "customer_id": tenant_id,
        "source": "github",
        "error_type": "Invalid signature",
    }
    initial_error_total = (
        REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) or 0
    )

    response = test_client.post(f"/webhooks/{tenant_id}/github", json=payload)

    assert response.status_code == 401
    assert (
        REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels)
        == initial_error_total + 1
    )


def test_receive_webhook_tenant_not_found(client):
    """Tests that a request with a non-existent tenant_id is rejected with 404."""
    test_client, mock_task, mock_verify_github, _ = client
    tenant_id = "non-existent-tenant"
    payload = {"action": "opened"}

    mock_verify_github.side_effect = HTTPException(
        status_code=404, detail="Tenant not found"
    )

    error_labels = {
        "customer_id": tenant_id,
        "source": "github",
        "error_type": "Tenant not found",
    }
    initial_error_total = (
        REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) or 0
    )

    response = test_client.post(f"/webhooks/{tenant_id}/github", json=payload)

    assert response.status_code == 404
    assert (
        REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels)
        == initial_error_total + 1
    )


def test_receive_stripe_webhook_success(client):
    """Tests successful reception and queuing of a Stripe webhook."""
    test_client, mock_task, _, mock_verify_stripe = client
    tenant_id = "some-tenant"
    payload = {"type": "customer.created"}

    initial_webhook_total = _counter_value(
        CUSTOMER_WEBHOOK_TOTAL, customer_id="mock_customer_id", source="stripe"
    )

    response = test_client.post(f"/webhooks/{tenant_id}/stripe", json=payload)

    assert response.status_code == 202
    assert response.json() == {"message": "Webhook received and queued for processing."}
    assert (
        _counter_value(
            CUSTOMER_WEBHOOK_TOTAL, customer_id="mock_customer_id", source="stripe"
        )
        == initial_webhook_total + 1
    )


def test_receive_stripe_webhook_invalid_signature(client):
    """Tests that a Stripe webhook with an invalid signature is rejected with 401."""
    test_client, mock_task, _, mock_verify_stripe = client
    tenant_id = "some-tenant"
    payload = {"type": "customer.created"}

    mock_verify_stripe.side_effect = HTTPException(
        status_code=401, detail="Invalid Stripe signature."
    )

    error_labels = {
        "customer_id": tenant_id,
        "source": "stripe",
        "error_type": "Invalid Stripe signature.",
    }
    initial_error_total = (
        REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) or 0
    )

    response = test_client.post(f"/webhooks/{tenant_id}/stripe", json=payload)

    assert response.status_code == 401
    assert (
        REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels)
        == initial_error_total + 1
    )


def test_receive_webhook_inactive_tenant(client):
    """Tests that a webhook for an inactive tenant is rejected with 403."""
    test_client, mock_task, mock_verify_github, _ = client
    tenant_id = "inactive-tenant"
    payload = {"action": "ping"}

    mock_verify_github.side_effect = HTTPException(
        status_code=403, detail="Tenant is inactive."
    )

    error_labels = {
        "customer_id": tenant_id,
        "source": "github",
        "error_type": "Tenant is inactive.",
    }
    initial_error_total = (
        REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels) or 0
    )

    response = test_client.post(f"/webhooks/{tenant_id}/github", json=payload)

    assert response.status_code == 403
    assert (
        REGISTRY.get_sample_value(_ERRORS_METRIC, labels=error_labels)
        == initial_error_total + 1
    )


def test_replay_event_success(client, db_session_mock, mocker):
    """Tests successful re-queuing of an event with authentication and tenant_id."""
    test_client, mock_task, _, _ = client
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
    db_session_mock.query.return_value.filter.return_value.first.return_value = (
        mock_event
    )

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 202
    assert response.json() == {
        "message": f"Event {event_id} has been re-queued for processing."
    }
    mock_task.delay.assert_called_once_with(mock_customer_id, mock_payload)


def test_replay_event_unauthorized(client):
    """Tests that replaying an event without authentication returns 401."""
    test_client, _, _, _ = client
    tenant_id = "some-tenant"
    event_id = 1

    # Remove auth override so the real get_current_user runs (no auth header → 401)
    app.main.app.dependency_overrides.pop(get_current_user, None)

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 401
    assert "Authorization header missing" in response.text


def test_replay_event_forbidden(client):
    """Tests that replaying an event with insufficient permissions returns 403."""
    test_client, _, _, _ = client
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
    test_client, _, _, _ = client
    tenant_id = "non-existent-tenant"
    event_id = 1

    mocker.patch("app.main.WebhookVerifier._get_customer", return_value=None)

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 404
    assert "Tenant not found or inactive." in response.text


def test_replay_event_event_not_found_for_tenant(client, db_session_mock, mocker):
    """Tests that replaying a non-existent event for a given tenant returns 404."""
    test_client, _, _, _ = client
    tenant_id = "some-tenant"
    event_id = 999
    mock_customer_id = "mock_customer_id"

    mock_customer = MagicMock(spec=Customer)
    mock_customer.id = mock_customer_id
    mock_customer.is_active = True
    mocker.patch("app.main.WebhookVerifier._get_customer", return_value=mock_customer)
    db_session_mock.query.return_value.filter.return_value.first.return_value = None

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 404
    assert "Event not found for this tenant" in response.text


def test_github_webhook_idempotent_duplicate(client, redis_mock):
    """동일 X-GitHub-Delivery ID로 두 번 요청 시 두 번째는 큐잉 없이 202 반환."""
    test_client, mock_task, _, _ = client
    tenant_id = "some-tenant"
    delivery_id = "abc-123-delivery"

    # 두 번째 요청: Redis에 이미 처리된 키 존재 (set nx=True가 False 반환)
    redis_mock.set.return_value = False

    response = test_client.post(
        f"/webhooks/{tenant_id}/github",
        json={"action": "opened"},
        headers={"X-GitHub-Delivery": delivery_id},
    )

    assert response.status_code == 202
    mock_task.apply_async.assert_not_called()


def test_stripe_webhook_idempotent_duplicate(client, redis_mock):
    """동일 Stripe event ID로 두 번 요청 시 두 번째는 큐잉 없이 202 반환."""
    test_client, mock_task, _, _ = client
    tenant_id = "some-tenant"

    # 두 번째 요청: Redis에 이미 처리된 키 존재 (set nx=True가 False 반환)
    redis_mock.set.return_value = False

    response = test_client.post(
        f"/webhooks/{tenant_id}/stripe",
        json={"id": "evt_duplicate_123", "type": "payment_intent.succeeded"},
    )

    assert response.status_code == 202
    mock_task.apply_async.assert_not_called()


def test_replay_event_data_isolation(client, db_session_mock, mocker):
    """Tests that events from other tenants return 404 (data isolation)."""
    test_client, _, _, _ = client
    tenant_id = "tenant-a"
    event_id = 1
    mock_customer_id_a = "customer_id_a"

    mock_customer_a = MagicMock(spec=Customer)
    mock_customer_a.id = mock_customer_id_a
    mock_customer_a.is_active = True
    mocker.patch("app.main.WebhookVerifier._get_customer", return_value=mock_customer_a)

    # Event belongs to a different customer — query returns None
    db_session_mock.query.return_value.filter.return_value.first.return_value = None

    response = test_client.post(f"/webhooks/{tenant_id}/events/{event_id}/replay")

    assert response.status_code == 404
    assert "Event not found for this tenant" in response.text
