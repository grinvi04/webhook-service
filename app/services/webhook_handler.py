import logging

from sqlalchemy.orm import Session

from ..celery_worker import celery
from ..database import SessionLocal
from ..models.webhook_event import WebhookEvent
from ..schemas.github_webhook import GitHubWebhookPayload

logger = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def process_github_webhook_task(self, payload_dict: dict):
    """
    Celery task to process a GitHub webhook payload.
    Retries on failure.
    """
    db: Session = SessionLocal()
    payload = GitHubWebhookPayload.model_validate(payload_dict)

    try:
        sender = payload.sender.get("login")
        repo = payload.repository.get("full_name")
        logger.info(f"Processing GitHub event from {sender} for repo {repo}")

        # 1. Save the event to DB
        db_event = WebhookEvent(source="github", payload=payload.model_dump())
        db.add(db_event)
        db.commit()
        db.refresh(db_event)
        logger.info(f"Saved webhook event {db_event.id} to database.")

        # 2. Add specific business logic here
        # e.g., if payload.action == 'created': send_slack_notification()

    except Exception as exc:
        logger.error(f"Task {self.request.id} failed: {exc}", exc_info=True)
        # Retry the task
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def process_stripe_webhook_task(self, payload_dict: dict):
    """
    Celery task to process a Stripe webhook payload.
    """
    db: Session = SessionLocal()
    event_type = payload_dict.get("type")

    try:
        logger.info(f"Processing Stripe event type: {event_type}")

        # 1. Save the event to DB
        db_event = WebhookEvent(source="stripe", payload=payload_dict)
        db.add(db_event)
        db.commit()
        db.refresh(db_event)
        logger.info(f"Saved webhook event {db_event.id} to database.")

        # 2. Add specific business logic here
        # e.g., if event_type == 'checkout.session.completed': provision_service()

    except Exception as exc:
        logger.error(f"Task {self.request.id} failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)
    finally:
        db.close()
