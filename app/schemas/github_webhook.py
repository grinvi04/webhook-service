from pydantic import BaseModel
from typing import Any, Dict

class GitHubWebhookPayload(BaseModel):
    """
    A generic schema for any GitHub webhook payload.
    Specific event payloads can inherit from this.
    """
    action: str | None = None
    sender: Dict[str, Any]
    repository: Dict[str, Any]
    # Add other common fields as needed
