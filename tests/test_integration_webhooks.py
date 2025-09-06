import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient # Changed from httpx import AsyncClient
from unittest.mock import MagicMock, patch, AsyncMock
import time
from fastapi import HTTPException

# Import app.main only within the fixture after patching
import app.main # Import the module, not the app instance directly
from app.config import settings
import app.webhook_registry # Import the registry to patch it

# Removed: pytestmark = pytest.mark.asyncio

# Removed: @pytest.fixture def anyio_backend(): return 'asyncio'

@pytest.fixture
def mock_app_dependencies(mocker):
    """
    Fixture to patch app dependencies before app.main is imported.
    """
    mock_task_instance = MagicMock()
    mock_delay_method = MagicMock()
    mock_task_instance.delay = mock_delay_method

    mock_verifier_instance = AsyncMock()

    # Patch TASK_REGISTRY and VERIFIER_REGISTRY directly
    mocker.patch.dict('app.webhook_registry.TASK_REGISTRY', {'github': mock_task_instance})
    mocker.patch.dict('app.webhook_registry.VERIFIER_REGISTRY', {'github': mock_verifier_instance})

    # Reload app.main to ensure it uses the patched dependencies
    import importlib
    importlib.reload(app.main)
    # Explicitly get the app instance after reloading
    app_instance = app.main.app
    yield mock_task_instance, mock_verifier_instance, app_instance # Yield the mocks and app instance
    # Teardown: clean up patches if necessary (mocker handles this)

# Removed async from function definition
def test_receive_github_webhook_success(mock_app_dependencies, mocker):
    """Tests successful reception and queuing of a GitHub webhook."""
    mock_task_instance, mock_verifier_instance, app_instance = mock_app_dependencies

    # 2. Prepare the payload and signature
    payload = {"action": "opened", "sender": {"login": "testuser"}, "repository": {"full_name": "test/repo"}}
    payload_bytes = json.dumps(payload).encode('utf-8')
    secret = settings.github_webhook_secret.encode('utf-8')
    signature = hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()
    headers = {
        'X-Hub-Signature-256': f'sha256={signature}',
        'Content-Type': 'application/json'
    }

    # 3. Make the request
    client = TestClient(app_instance) # Changed from AsyncClient
    # Removed async with client as ac:
    response = client.post("/webhooks/github", content=payload_bytes, headers=headers) # Removed await and changed ac to client

    # 4. Assertions
    assert response.status_code == 202
    assert response.json() == {"message": "Webhook received and queued for processing."}
    
    # Verify the task was called once with the correct payload
    mock_task_instance.delay.assert_called_once_with(payload)


# Removed async from function definition
def test_receive_github_webhook_invalid_signature(mock_app_dependencies, mocker):
    """Tests that a request with an invalid signature is rejected."""
    mock_task_instance, mock_verifier_instance, app_instance = mock_app_dependencies
    
    # Configure mock_verifier_instance to raise HTTPException
    mock_verifier_instance.side_effect = HTTPException(status_code=401, detail="Invalid GitHub signature")

    payload = {"action": "opened"}
    payload_bytes = json.dumps(payload).encode('utf-8')
    secret = settings.github_webhook_secret.encode('utf-8')
    signature = hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()
    headers = {
        'X-Hub-Signature-256': 'sha256=invalid_signature',
        'Content-Type': 'application/json'
    }

    client = TestClient(app_instance) # Changed from AsyncClient
    # Removed async with client as ac:
    response = client.post("/webhooks/github", content=payload_bytes, headers=headers) # Removed await and changed ac to client

    assert response.status_code == 401
    assert "Invalid GitHub signature" in response.text
    mock_task_instance.delay.assert_not_called()