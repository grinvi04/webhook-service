from unittest.mock import MagicMock, patch

import pytest

from app.metrics import CUSTOMER_WEBHOOK_ERRORS_TOTAL
from app.models.webhook_event import WebhookEvent
from app.services.webhook_handler import process_github_webhook_task


def _counter_value(counter, **labels):
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == labels:
                return sample.value
    return 0.0


def test_process_github_webhook_task_success():
    """Tests the logic of the GitHub webhook task itself."""
    mock_db_session = MagicMock()
    customer_id = "test_customer_123"
    payload = {
        "action": "starred",
        "sender": {"login": "testuser"},
        "repository": {"full_name": "test/repo"},
    }

    with patch(
        "app.services.webhook_handler.SessionLocal", return_value=mock_db_session
    ):
        process_github_webhook_task.run(customer_id, payload)

    mock_db_session.add.assert_called_once()
    added_object = mock_db_session.add.call_args[0][0]
    assert isinstance(added_object, WebhookEvent)
    assert added_object.customer_id == customer_id
    assert added_object.source == "github"
    assert added_object.payload == payload

    mock_db_session.commit.assert_called_once()
    mock_db_session.close.assert_called_once()


def test_process_github_webhook_task_failure_metrics():
    """Tests that CUSTOMER_WEBHOOK_ERRORS_TOTAL is incremented on task failure."""
    mock_db_session = MagicMock()
    customer_id = "test_customer_123"
    payload = {"invalid_key": "value"}

    initial_error_total = _counter_value(
        CUSTOMER_WEBHOOK_ERRORS_TOTAL,
        customer_id=customer_id,
        source="github",
        error_type="ValueError",
    )

    with (
        patch(
            "app.services.webhook_handler.SessionLocal", return_value=mock_db_session
        ),
        patch(
            "app.services.webhook_handler.GitHubWebhookPayload.model_validate",
            side_effect=ValueError("Validation Error"),
        ),
    ):
        with pytest.raises(ValueError):
            process_github_webhook_task.run(customer_id, payload)

    assert (
        _counter_value(
            CUSTOMER_WEBHOOK_ERRORS_TOTAL,
            customer_id=customer_id,
            source="github",
            error_type="ValueError",
        )
        == initial_error_total + 1
    )

    mock_db_session.close.assert_called_once()
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_called()
