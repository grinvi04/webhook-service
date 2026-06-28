import logging

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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
def process_github_webhook_task(
    self, customer_id: str, payload_dict: dict, event_id: str | None = None
) -> None:
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

        db_event = WebhookEventRepository.create(
            db,
            customer_id=customer_id,
            source="github",
            payload=payload.model_dump(),
            event_id=event_id,
        )
        db.commit()
        db.refresh(db_event)
        logger.info(
            "Saved webhook event %s for customer %s to database.",
            db_event.id,
            customer_id,
        )

    except IntegrityError:
        # 멱등 고유제약 위반 — 동일 (customer, source, event_id) 이미 적재됨.
        # 재시도/DLQ 대상이 아니라 정상 중복으로 간주하고 조용히 종료.
        db.rollback()
        logger.info(
            "Duplicate github event ignored (unique constraint): customer=%s event_id=%s",
            customer_id,
            event_id,
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
def process_stripe_webhook_task(
    self, customer_id: str, payload_dict: dict, event_id: str | None = None
) -> None:
    db: Session = SessionLocal()
    try:
        payload = StripeWebhookPayload.model_validate(payload_dict)
        logger.info(
            "Processing Stripe event type: %s for customer %s",
            payload.type,
            customer_id,
        )

        db_event = WebhookEventRepository.create(
            db,
            customer_id=customer_id,
            source="stripe",
            payload=payload.model_dump(),
            event_id=event_id,
        )
        db.commit()
        db.refresh(db_event)
        logger.info(
            "Saved webhook event %s for customer %s to database.",
            db_event.id,
            customer_id,
        )

    except IntegrityError:
        # 멱등 고유제약 위반 — 동일 (customer, source, event_id) 이미 적재됨.
        db.rollback()
        logger.info(
            "Duplicate stripe event ignored (unique constraint): customer=%s event_id=%s",
            customer_id,
            event_id,
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
