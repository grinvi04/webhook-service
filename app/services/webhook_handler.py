import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from ..celery_worker import celery
from ..database import SessionLocal
from ..metrics import CUSTOMER_WEBHOOK_ERRORS_TOTAL
from ..models.webhook_event import WebhookEvent
from ..schemas.github_webhook import GitHubWebhookPayload

logger = logging.getLogger(__name__)


@celery.task(name="tasks.send_to_dlq")
def send_to_dlq(failed_task_data: dict):
    logger.error(f"Task sent to DLQ: {failed_task_data}")


def _handle_task_failure(task, exc, task_id, args, kwargs, einfo):
    # 실패 메트릭 증가
    customer_id = args[0] if args else "Unknown"
    source = task.name.split('.')[-1].replace('_webhook_task', '') # 태스크 이름에서 source 추출
    CUSTOMER_WEBHOOK_ERRORS_TOTAL.labels(
        customer_id=str(customer_id),
        source=source,
        error_type=str(type(exc).__name__)
    ).inc()
    # ... (나머지 기존 코드) ...


@celery.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    on_failure=_handle_task_failure,
    acks_late=True,
)
def process_github_webhook_task(self, customer_id: UUID, payload_dict: dict):
    """
    Celery task to process a GitHub webhook payload for a specific customer.
    """
    db: Session = SessionLocal()
    try:
        payload = GitHubWebhookPayload.model_validate(payload_dict)
        sender = payload.sender.get("login")
        repo = payload.repository.get("full_name")
        logger.info(
            f"Processing GitHub event from {sender} for repo {repo} for customer {customer_id}"
        )

        db_event = WebhookEvent(
            customer_id=customer_id, source="github", payload=payload.model_dump()
        )
        db.add(db_event)
        db.commit()
        db.refresh(db_event)
        logger.info(
            f"Saved webhook event {db_event.id} for customer {customer_id} to database."
        )

    except Exception as e:
        CUSTOMER_WEBHOOK_ERRORS_TOTAL.labels(
            customer_id=str(customer_id),
            source="github",
            error_type=type(e).__name__,
        ).inc()
        raise
    finally:
        db.close()


@celery.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    on_failure=_handle_task_failure,
    acks_late=True,
)
def process_stripe_webhook_task(self, customer_id: UUID, payload_dict: dict):
    """
    Celery task to process a Stripe webhook payload for a specific customer.
    """
    db: Session = SessionLocal()
    try:
        event_type = payload_dict.get("type")
        logger.info(
            f"Processing Stripe event type: {event_type} for customer {customer_id}"
        )

        db_event = WebhookEvent(
            customer_id=customer_id, source="stripe", payload=payload_dict
        )
        db.add(db_event)
        db.commit()
        db.refresh(db_event)
        logger.info(
            f"Saved webhook event {db_event.id} for customer {customer_id} to database."
        )

    except Exception:
        # The on_failure handler will be called automatically by Celery.
        raise
    finally:
        db.close()
