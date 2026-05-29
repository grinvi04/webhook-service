from unittest.mock import MagicMock, patch

import pytest # pytest 임포트 추가
from prometheus_client import REGISTRY # REGISTRY 임포트 추가

from app.models.webhook_event import WebhookEvent
from app.services.webhook_handler import process_github_webhook_task
from app.metrics import CUSTOMER_WEBHOOK_ERRORS_TOTAL


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
        # Execute the task with both customer_id and payload
        process_github_webhook_task.run(customer_id, payload)

    # Assertions
    mock_db_session.add.assert_called_once()
    added_object = mock_db_session.add.call_args[0][0]
    assert isinstance(added_object, WebhookEvent)
    assert added_object.customer_id == customer_id  # Verify customer_id is set
    assert added_object.source == "github"
    assert added_object.payload == payload

    mock_db_session.commit.assert_called_once()
    mock_db_session.close.assert_called_once()


def test_process_github_webhook_task_failure_metrics():
    """Tests that CUSTOMER_WEBHOOK_ERRORS_TOTAL is incremented on task failure."""
    mock_db_session = MagicMock()
    customer_id = "test_customer_123"
    payload = {"invalid_key": "value"} # 유효하지 않은 페이로드로 예외 발생 유도

    # Get initial error metric value
    initial_error_total = REGISTRY.get_sample_value(
        "customer_webhook_errors_total", labels={"customer_id": customer_id, "source": "github", "error_type": "ValueError"}
    ) or 0

    with patch(
        "app.services.webhook_handler.SessionLocal", return_value=mock_db_session
    ), patch(
        "app.services.webhook_handler.GitHubWebhookPayload.model_validate",
        side_effect=ValueError("Validation Error") # 예외 발생 모킹
    ):
        # Celery 태스크는 예외 발생 시 재시도 로직을 따르므로, 직접 호출 시 예외가 발생해야 합니다.
        with pytest.raises(ValueError):
            process_github_webhook_task.run(customer_id, payload)

    # Verify error metric
    assert REGISTRY.get_sample_value(
        "customer_webhook_errors_total", labels={"customer_id": customer_id, "source": "github", "error_type": "ValueError"}
    ) == initial_error_total + 1

    mock_db_session.close.assert_called_once() # 실패 시에도 세션은 닫혀야 합니다。
    mock_db_session.add.assert_not_called() # 실패 시 DB에 추가되지 않아야 합니다。
    mock_db_session.commit.assert_not_called() # 실패 시 커밋되지 않아야 합니다。
