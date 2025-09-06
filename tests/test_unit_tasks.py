import pytest
from unittest.mock import MagicMock, patch

from app.services.webhook_handler import process_github_webhook_task
from app.models.webhook_event import WebhookEvent


def test_process_github_webhook_task_success():
    """Tests the logic of the GitHub webhook task itself."""
    # 1. Mock the database session
    mock_db_session = MagicMock()
    
    # 2. Define a sample payload
    payload = {"action": "starred", "sender": {"login": "testuser"}, "repository": {"full_name": "test/repo"}}

    # 3. Patch the SessionLocal to return our mock session
    with patch('app.services.webhook_handler.SessionLocal', return_value=mock_db_session):
        # 4. Execute the task synchronously using .run()
        process_github_webhook_task.run(payload)

    # 6. Assertions
    # Verify that a WebhookEvent object was added to the session
    mock_db_session.add.assert_called_once()
    added_object = mock_db_session.add.call_args[0][0]
    assert isinstance(added_object, WebhookEvent)
    assert added_object.source == "github"
    assert added_object.payload == payload

    # Verify that the session was committed
    mock_db_session.commit.assert_called_once()
    mock_db_session.close.assert_called_once()
