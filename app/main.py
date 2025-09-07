import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import admin, database
from .logging_config import setup_logging
from .models.webhook_event import WebhookEvent
from .webhook_registry import get_task, get_verifier

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Webhook Service",
    description="A service to receive and process webhooks from multiple providers.",
    version="2.2.0",
)

# Add Admin UI
admin.setup_admin(app, database.engine)

# Add Prometheus metrics
Instrumentator().instrument(app).expose(app)


@app.on_event("startup")
async def startup():
    logger.info("Application startup.")


@app.get("/", tags=["Root"])
async def read_root():
    """
    Root endpoint to check if the service is running.
    """
    logger.info("Root endpoint was hit.")
    return {"message": "Webhook service is running."}


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint to verify service status.
    """
    try:
        # Check DB connection
        with database.SessionLocal() as db:
            db.execute(text("SELECT 1"))
        logger.info("Health check successful.")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service Unavailable")


# --- Webhook Endpoints --- #


@app.post(
    "/webhooks/{source}",
    tags=["Webhooks"],
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_webhook(source: str, request: Request, payload: dict[Any, Any]):
    """
    Receives webhooks from any registered source, verifies them,
    and queues them for processing.
    """
    try:
        verifier = get_verifier(source)
        await verifier(request)  # Manually call the verifier dependency
    except NotImplementedError:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not supported.")

    logger.info(f"Received {source} webhook. Queuing for processing.")
    task = get_task(source)
    task.delay(payload)
    return {"message": "Webhook received and queued for processing."}


@app.post(
    "/events/{event_id}/replay", tags=["Events"], status_code=status.HTTP_202_ACCEPTED
)
def replay_event(event_id: int, db: Session = Depends(database.get_db)):
    """
    Re-queues a specific event for processing.
    """
    logger.info(f"Attempting to replay event_id: {event_id}")
    db_event = db.query(WebhookEvent).filter(WebhookEvent.id == event_id).first()

    if not db_event:
        logger.warning(f"Event with id {event_id} not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )

    try:
        task = get_task(db_event.source)
        task.delay(db_event.payload)
    except NotImplementedError:
        logger.error(f"Replay not implemented for source: {db_event.source}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Replay not implemented for source '{db_event.source}'",
        )

    logger.info(f"Successfully re-queued event_id: {event_id}")
    return {"message": f"Event {event_id} has been re-queued for processing."}
