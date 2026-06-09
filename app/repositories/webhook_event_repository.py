from uuid import UUID

from sqlalchemy.orm import Session

from ..models.webhook_event import WebhookEvent


class WebhookEventRepository:
    """WebhookEvent 데이터 접근 전용.

    세션은 호출부가 소유(주입)하며, 트랜잭션 커밋 경계도 create 안에서 닫는다.
    """

    def create(
        self, db: Session, *, customer_id: UUID, source: str, payload: dict
    ) -> WebhookEvent:
        event = WebhookEvent(customer_id=customer_id, source=source, payload=payload)
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    def get_for_customer(
        self, db: Session, *, event_id: int, customer_id: UUID
    ) -> WebhookEvent | None:
        return (
            db.query(WebhookEvent)
            .filter(
                WebhookEvent.id == event_id,
                WebhookEvent.customer_id == customer_id,
            )
            .first()
        )
