from sqlalchemy import Column, Integer, String, JSON, DateTime
from sqlalchemy.sql import func
from ..database import Base

class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, index=True)  # e.g., "github", "stripe"
    payload = Column(JSON)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
