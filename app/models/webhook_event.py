from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    # 멱등 고유제약 — Redis TTL 만료 후 재시도가 중복행을 만드는 것을 막는 backstop.
    # event_id NULL 행(공급자 ID 미제공)은 NULL distinct 규칙으로 충돌하지 않는다.
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "source",
            "event_id",
            name="uq_webhook_events_customer_source_event",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False, index=True)
    source = Column(String, index=True)
    event_id = Column(String, index=True, nullable=True)
    payload = Column(JSON)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    status = Column(String, default="PENDING", index=True, nullable=False)

    customer = relationship("Customer", back_populates="events")
