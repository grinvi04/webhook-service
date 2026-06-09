from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.webhook_event import WebhookEvent
from app.repositories.customer_repository import CustomerRepository
from app.repositories.webhook_event_repository import WebhookEventRepository


def test_customer_repo_get_by_tenant_id():
    db = MagicMock()
    sentinel = object()
    db.query.return_value.filter.return_value.first.return_value = sentinel

    result = CustomerRepository().get_by_tenant_id(db, "tenant-1")

    assert result is sentinel
    db.query.return_value.filter.return_value.first.assert_called_once()


@pytest.mark.asyncio
async def test_customer_repo_get_by_tenant_id_async():
    db = MagicMock()
    sentinel = object()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = sentinel
    db.execute = AsyncMock(return_value=exec_result)

    result = await CustomerRepository().get_by_tenant_id_async(db, "tenant-1")

    assert result is sentinel
    db.execute.assert_awaited_once()


def test_webhook_event_repo_create_persists_and_returns_event():
    db = MagicMock()
    customer_id = uuid4()
    payload = {"action": "starred"}

    event = WebhookEventRepository().create(
        db, customer_id=customer_id, source="github", payload=payload
    )

    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert isinstance(added, WebhookEvent)
    assert added.customer_id == customer_id
    assert added.source == "github"
    assert added.payload == payload
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(added)
    assert event is added


def test_webhook_event_repo_get_for_customer_filters():
    db = MagicMock()
    sentinel = object()
    db.query.return_value.filter.return_value.first.return_value = sentinel
    customer_id = uuid4()

    result = WebhookEventRepository().get_for_customer(
        db, event_id=7, customer_id=customer_id
    )

    assert result is sentinel
    db.query.return_value.filter.return_value.first.assert_called_once()
