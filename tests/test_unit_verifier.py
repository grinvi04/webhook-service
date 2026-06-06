from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.dependencies import WebhookVerifier
from app.models.customer import Customer


@pytest.fixture
def verifier():
    return WebhookVerifier(source="github")


@pytest.fixture
def mock_db():
    return AsyncMock()


def _make_customer(is_active=True):
    c = MagicMock(spec=Customer)
    c.is_active = is_active
    c.tenant_id = "tenant-1"
    c.id = "cust-1"
    return c


async def test_get_customer_async_returns_active_customer(verifier, mock_db):
    customer = _make_customer(is_active=True)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = customer
    mock_db.execute.return_value = mock_result

    result = await verifier._get_customer_async(mock_db, "tenant-1")

    assert result is customer


async def test_get_customer_async_returns_none_when_not_found(verifier, mock_db):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    result = await verifier._get_customer_async(mock_db, "unknown")

    assert result is None


async def test_get_customer_async_raises_403_for_inactive_tenant(verifier, mock_db):
    customer = _make_customer(is_active=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = customer
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await verifier._get_customer_async(mock_db, "tenant-1")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Tenant is inactive."
