"""멱등성·유실 방지 (PR-2 / M1, L4).

- 큐잉 실패 시 예약한 Redis 멱등키를 해제해 공급자 재시도가 드롭되지 않음
- 멱등키에 tenant_id 포함(L4)
- webhook_events (customer_id, source, event_id) 고유제약이 중복행을 차단
- 태스크는 고유제약 위반(IntegrityError)을 DLQ가 아니라 정상 중복으로 흡수
"""

import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.database
import app.main
from app.database import Base
from app.dependencies import get_redis
from app.models.customer import Customer  # noqa: F401 — Base 등록 필수
from app.models.webhook_event import WebhookEvent
from app.repositories.webhook_event_repository import WebhookEventRepository
from app.services.webhook_handler import process_github_webhook_task

TEST_SECRET = "test-webhook-secret-0123456789abcdef"  # noqa: S105 (테스트 전용 더미)


def _github_signature(body: bytes, secret: str = TEST_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class _FakeAsyncDB:
    def __init__(self, customer):
        self.customer = customer

    async def execute(self, *args, **kwargs):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.customer
        return result


# ─── 통합: 큐잉 실패 시 멱등키 해제 (AC-M1) ──────────────────────────────────


@pytest.fixture
def queue_failure_client(mocker):
    customer = MagicMock(spec=Customer)
    customer.id = "mock_customer_id"
    customer.is_active = True
    customer.webhook_secret = TEST_SECRET

    redis_mock = MagicMock()
    redis_mock.set = AsyncMock(return_value=True)  # 예약 성공
    redis_mock.delete = AsyncMock(return_value=1)

    app.main.app.dependency_overrides[get_redis] = lambda: redis_mock
    app.main.app.dependency_overrides[app.database.get_async_db] = lambda: _FakeAsyncDB(
        customer
    )

    # 큐잉 실패 시뮬레이션 — apply_async가 예외 발생
    failing_task = MagicMock()
    failing_task.apply_async.side_effect = RuntimeError("broker down")
    mocker.patch("app.main.get_task", return_value=failing_task)

    test_client = TestClient(app.main.app, raise_server_exceptions=False)
    yield test_client, redis_mock

    app.main.app.dependency_overrides.clear()


def test_idempotency_key_released_on_queue_failure(queue_failure_client):
    """큐잉(apply_async) 실패 시 예약한 멱등키를 삭제해 재시도가 드롭되지 않게 한다."""
    test_client, redis_mock = queue_failure_client
    tenant_id = "some-tenant"
    delivery_id = "delivery-xyz"
    body = json.dumps({"action": "opened"}).encode("utf-8")

    response = test_client.post(
        f"/webhooks/{tenant_id}/github",
        content=body,
        headers={
            "content-type": "application/json",
            "X-Hub-Signature-256": _github_signature(body),
            "X-GitHub-Delivery": delivery_id,
        },
    )

    # 공급자가 재시도하도록 5xx로 응답
    assert response.status_code == 500
    # 예약했던 키를 해제 — 키에 tenant_id 포함(L4)
    expected_key = f"webhook:idempotency:{tenant_id}:github:{delivery_id}"
    redis_mock.delete.assert_awaited_once_with(expected_key)


# ─── DB 고유제약 (AC-M1 backstop) ────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _make_customer(session, tenant_id="tenant-1"):
    customer = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Test",
        webhook_secret="secret",
        allowed_event_types=[],
    )
    session.add(customer)
    session.flush()
    return customer


def test_duplicate_event_id_violates_unique_constraint(db):
    """동일 (customer_id, source, event_id) 두 번째 적재 → IntegrityError."""
    customer = _make_customer(db)
    WebhookEventRepository.create(
        db, customer_id=customer.id, source="github", payload={}, event_id="evt-1"
    )
    db.commit()

    WebhookEventRepository.create(
        db, customer_id=customer.id, source="github", payload={}, event_id="evt-1"
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_null_event_id_does_not_conflict(db):
    """event_id NULL 행은 NULL distinct 규칙으로 충돌하지 않는다."""
    customer = _make_customer(db)
    WebhookEventRepository.create(
        db, customer_id=customer.id, source="github", payload={}, event_id=None
    )
    WebhookEventRepository.create(
        db, customer_id=customer.id, source="github", payload={}, event_id=None
    )
    db.commit()

    count = (
        db.query(WebhookEvent).filter(WebhookEvent.customer_id == customer.id).count()
    )
    assert count == 2


def test_event_id_persisted(db):
    """엔드포인트에서 추출한 event_id가 적재된다."""
    customer = _make_customer(db)
    evt = WebhookEventRepository.create(
        db, customer_id=customer.id, source="github", payload={}, event_id="evt-42"
    )
    db.commit()
    db.refresh(evt)

    assert evt.event_id == "evt-42"


# ─── 태스크: 고유제약 위반은 DLQ가 아니라 정상 중복으로 흡수 ─────────────────


def test_task_swallows_integrity_error_as_duplicate():
    """commit이 IntegrityError를 내면 태스크는 재시도/DLQ 없이 rollback 후 종료."""
    mock_db = MagicMock()
    mock_db.commit.side_effect = IntegrityError("dup", None, Exception())
    payload = {
        "action": "opened",
        "sender": {"login": "octocat"},
        "repository": {"full_name": "octocat/hello"},
    }

    with patch("app.services.webhook_handler.SessionLocal", return_value=mock_db):
        # 예외가 전파되지 않아야 함 (autoretry/DLQ 미발동)
        process_github_webhook_task.run("cust-1", payload, "evt-dup")

    mock_db.rollback.assert_called_once()
    mock_db.close.assert_called_once()
