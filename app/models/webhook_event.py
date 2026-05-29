from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True
    )
    source = Column(String, index=True)
    payload = Column(JSON)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    status = Column(String, default="PENDING", index=True, nullable=False)

    customer = relationship("Customer", back_populates="events")
