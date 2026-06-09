import logging
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..celery_worker import celery
from ..database import SessionLocal
from ..metrics import CUSTOMER_WEBHOOK_ERRORS_TOTAL
from ..repositories.webhook_event_repository import WebhookEventRepository
from ..schemas.github_webhook import GitHubWebhookPayload
from ..schemas.stripe_webhook import StripeWebhookPayload

logger = logging.getLogger(__name__)


@celery.task(name="tasks.send_to_dlq")
def send_to_dlq(failed_task_data: dict):
    logger.error("Task sent to DLQ: %s", failed_task_data)


def _handle_task_failure(task, exc, task_id, args, kwargs, einfo):
    customer_id = args[0] if args else "Unknown"
    send_to_dlq.apply_async(
        args=[
            {
                "task_name": task.name,
                "task_id": task_id,
                "customer_id": str(customer_id),
                "error": str(exc),
            }
        ],
        queue="dead_letters",
    )


@celery.task(
    bind=True,
    max_retries=3,
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    on_failure=_handle_task_failure,
    acks_late=True,
)
def process_github_webhook_task(self, customer_id: UUID, payload_dict: dict):
    db: Session = SessionLocal()
    try:
        payload = GitHubWebhookPayload.model_validate(payload_dict)
        sender = payload.sender.get("login")
        repo = payload.repository.get("full_name")
        logger.info(
            "Processing GitHub event from %s for repo %s for customer %s",
            sender,
            repo,
            customer_id,
        )

        db_event = WebhookEventRepository().create(
            db, customer_id=customer_id, source="github", payload=payload.model_dump()
        )
        logger.info(
            "Saved webhook event %s for customer %s to database.",
            db_event.id,
            customer_id,
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
    autoretry_for=(SQLAlchemyError,),
    retry_backoff=True,
    on_failure=_handle_task_failure,
    acks_late=True,
)
def process_stripe_webhook_task(self, customer_id: UUID, payload_dict: dict):
    db: Session = SessionLocal()
    try:
        payload = StripeWebhookPayload.model_validate(payload_dict)
        logger.info(
            "Processing Stripe event type: %s for customer %s",
            payload.type,
            customer_id,
        )

        db_event = WebhookEventRepository().create(
            db, customer_id=customer_id, source="stripe", payload=payload.model_dump()
        )
        logger.info(
            "Saved webhook event %s for customer %s to database.",
            db_event.id,
            customer_id,
        )

    except Exception as e:
        CUSTOMER_WEBHOOK_ERRORS_TOTAL.labels(
            customer_id=str(customer_id),
            source="stripe",
            error_type=type(e).__name__,
        ).inc()
        raise
    finally:
        db.close()
