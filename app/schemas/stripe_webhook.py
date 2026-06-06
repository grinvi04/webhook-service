from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class StripeWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    data: dict[str, Any] = {}
