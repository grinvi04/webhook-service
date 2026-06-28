from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.webhook_event import WebhookEvent


class WebhookEventRepository:
    """WebhookEvent 데이터 접근 전용.

    세션은 호출부가 소유(주입)한다. create는 add만 수행하고, commit/refresh 등
    트랜잭션 경계는 세션을 소유한 호출부(Celery Task 등)가 제어한다.
    """

    @classmethod
    def create(
        cls,
        db: Session,
        *,
        customer_id: UUID,
        source: str,
        payload: dict,
        event_id: str | None = None,
    ) -> WebhookEvent:
        event = WebhookEvent(
            customer_id=customer_id,
            source=source,
            payload=payload,
            event_id=event_id,
        )
        db.add(event)
        return event

    @classmethod
    def get_for_customer(
        cls, db: Session, *, event_id: int, customer_id: UUID
    ) -> WebhookEvent | None:
        return db.execute(
            select(WebhookEvent).where(
                WebhookEvent.id == event_id,
                WebhookEvent.customer_id == customer_id,
            )
        ).scalar_one_or_none()
