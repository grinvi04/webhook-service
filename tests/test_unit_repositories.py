import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.customer import Customer  # noqa: F401 — Base 등록 필수
from app.models.webhook_event import WebhookEvent  # noqa: F401
from app.repositories.customer_repository import CustomerRepository
from app.repositories.webhook_event_repository import WebhookEventRepository


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


def _make_customer(session: object, tenant_id: str = "tenant-1") -> Customer:
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


# ─── CustomerRepository ──────────────────────────────────────────────────────


def test_customer_repo_get_by_tenant_id(db):
    _make_customer(db, "tenant-1")

    result = CustomerRepository.get_by_tenant_id(db, "tenant-1")

    assert result is not None
    assert result.tenant_id == "tenant-1"


def test_customer_repo_get_by_tenant_id_not_found(db):
    result = CustomerRepository.get_by_tenant_id(db, "nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_customer_repo_get_by_tenant_id_async():
    sentinel = object()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = sentinel
    db = MagicMock()
    db.execute = AsyncMock(return_value=exec_result)

    result = await CustomerRepository.get_by_tenant_id_async(db, "tenant-1")

    assert result is sentinel
    db.execute.assert_awaited_once()


# ─── WebhookEventRepository ──────────────────────────────────────────────────


def test_webhook_event_repo_create_returns_event_pending(db):
    customer = _make_customer(db)
    payload = {"action": "starred"}

    result = WebhookEventRepository.create(
        db, customer_id=customer.id, source="github", payload=payload
    )

    assert isinstance(result, WebhookEvent)
    assert result.customer_id == customer.id
    assert result.source == "github"
    assert result.payload == payload
    # create는 add만 수행 — flush 전이므로 id 미할당(pending)
    assert result in db.new


def test_webhook_event_repo_create_does_not_auto_commit(db):
    from sqlalchemy import text

    customer = _make_customer(db)

    WebhookEventRepository.create(db, customer_id=customer.id, source="github", payload={})
    db.rollback()

    remaining = db.execute(text("SELECT COUNT(*) FROM webhook_events")).scalar()
    assert remaining == 0


def test_webhook_event_repo_get_for_customer_found(db):
    customer = _make_customer(db)
    evt = WebhookEventRepository.create(db, customer_id=customer.id, source="github", payload={})
    db.flush()

    result = WebhookEventRepository.get_for_customer(db, event_id=evt.id, customer_id=customer.id)

    assert result is not None
    assert result.id == evt.id
    assert result.source == "github"


def test_webhook_event_repo_get_for_customer_wrong_customer(db):
    customer = _make_customer(db)
    evt = WebhookEventRepository.create(db, customer_id=customer.id, source="github", payload={})
    db.flush()

    result = WebhookEventRepository.get_for_customer(db, event_id=evt.id, customer_id=uuid.uuid4())

    assert result is None


def test_webhook_event_repo_get_for_customer_wrong_event_id(db):
    customer = _make_customer(db)
    WebhookEventRepository.create(db, customer_id=customer.id, source="github", payload={})
    db.flush()

    result = WebhookEventRepository.get_for_customer(db, event_id=99999, customer_id=customer.id)

    assert result is None
