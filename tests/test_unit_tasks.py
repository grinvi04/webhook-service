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

    with patch("app.services.webhook_handler.SessionLocal", return_value=mock_db_session):
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
        patch("app.services.webhook_handler.SessionLocal", return_value=mock_db_session),
        patch(
            "app.services.webhook_handler.GitHubWebhookPayload.model_validate",
            side_effect=ValueError("Validation Error"),
        ),
        pytest.raises(ValueError),
    ):
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


def test_process_github_webhook_task_marks_processed():
    """성공 처리 시 webhook_event.status가 PROCESSED로 전이된다."""
    mock_db_session = MagicMock()
    payload = {
        "action": "starred",
        "sender": {"login": "testuser"},
        "repository": {"full_name": "test/repo"},
    }

    with patch("app.services.webhook_handler.SessionLocal", return_value=mock_db_session):
        process_github_webhook_task.run("test_customer_123", payload)

    added_object = mock_db_session.add.call_args[0][0]
    assert added_object.status == "PROCESSED"
    mock_db_session.commit.assert_called_once()


def test_process_github_webhook_task_marks_failed():
    """비일시적 오류로 처리 실패 시 status가 FAILED로 전이된다."""
    mock_db_session = MagicMock()
    # 첫 commit(성공 경로)은 실패, FAILED 기록용 두 번째 commit은 성공.
    mock_db_session.commit.side_effect = [RuntimeError("boom"), None]
    payload = {
        "action": "starred",
        "sender": {"login": "testuser"},
        "repository": {"full_name": "test/repo"},
    }

    with (
        patch("app.services.webhook_handler.SessionLocal", return_value=mock_db_session),
        pytest.raises(RuntimeError),
    ):
        process_github_webhook_task.run("test_customer_123", payload)

    # create()로 추가된 이벤트가 FAILED로 표시되어야 한다.
    added_object = mock_db_session.add.call_args_list[0][0][0]
    assert isinstance(added_object, WebhookEvent)
    assert added_object.status == "FAILED"
    mock_db_session.rollback.assert_called()
