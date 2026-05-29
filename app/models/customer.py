import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    webhook_secret = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)  # is_active 필드 추가
    created_at = Column(DateTime, default=datetime.utcnow)

    allowed_event_types = Column(JSON, default=list, nullable=False)

    events = relationship("WebhookEvent", back_populates="customer")
