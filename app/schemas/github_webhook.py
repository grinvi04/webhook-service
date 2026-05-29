from typing import Any

from pydantic import BaseModel


class GitHubWebhookPayload(BaseModel):
    """
    A generic schema for any GitHub webhook payload.
    Specific event payloads can inherit from this.
    """

    action: str | None = None
    sender: dict[str, Any]
    repository: dict[str, Any]
    # Add other common fields as needed
