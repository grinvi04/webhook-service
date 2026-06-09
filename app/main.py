import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from keycloak import KeycloakOpenID

from . import admin, database, webhooks  # noqa: F401
from .config import settings
from .dependencies import (
    WebhookVerifier,
    get_current_user,
    get_redis,
    get_tenant_id_from_path,
    limiter,
)
from .logging_config import setup_logging
from .metrics import (
    CUSTOMER_WEBHOOK_ERRORS_TOTAL,
    CUSTOMER_WEBHOOK_TOTAL,
    WEBHOOK_PROCESSING_DURATION,
)
from .repositories.webhook_event_repository import WebhookEventRepository
from .webhook_registry import get_task

setup_logging()
logger = logging.getLogger(__name__)

verify_github = WebhookVerifier(source="github")
verify_stripe = WebhookVerifier(source="stripe")

keycloak_openid = KeycloakOpenID(
    server_url=f"{settings.keycloak_url}/realms/{settings.keycloak_realm}",
    client_id=settings.keycloak_client_id,
    realm_name=settings.keycloak_realm,
    client_secret_key=settings.keycloak_client_secret,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup.")
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    yield
    await app.state.redis.close()
    logger.info("Application shutdown.")


app = FastAPI(
    title="Webhook Service",
    description="A service to receive and process webhooks from multiple providers.",
    version="3.0.0",
    lifespan=lifespan,
)

# Add KeycloakOpenID to app.state
app.state.keycloak_openid = keycloak_openid

# Add Admin UI
admin.setup_admin(app, database.engine)

# Add Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Add Rate Limiting Middleware
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# SessionMiddleware required for request.session usage in admin.py
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


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
        logger.error("Health check failed: %s", e)
        raise HTTPException(status_code=503, detail="Service Unavailable")


# --- Webhook Endpoints --- #


def _extract_event_id(source: str, request: Request, payload: dict) -> str | None:
    if source == "github":
        return request.headers.get("X-GitHub-Delivery")
    if source == "stripe":
        return payload.get("id")
    return None


@app.post(
    "/webhooks/{tenant_id}/{source}",
    tags=["Webhooks"],
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("120/minute")  # Override default limit for this specific endpoint
async def receive_webhook(
    tenant_id: str,
    source: str,
    request: Request,
    payload: dict[Any, Any],
    db: AsyncSession = Depends(database.get_async_db),
    redis_client: aioredis.Redis = Depends(get_redis),
):
    """
    Receives webhooks from a specific tenant and source, verifies them,
    and queues them for processing.
    """
    start_time = time.time()  # 시간 측정 시작
    try:
        # The verifier dependency will handle tenant validation and signature checks.
        if source == "github":
            customer = await verify_github(request, tenant_id, db)
        elif source == "stripe":
            customer = await verify_stripe(request, tenant_id, db)
        else:
            raise HTTPException(
                status_code=404, detail=f"Source '{source}' not supported."
            )

        # Idempotency check — 중복 웹훅 방지 (Stripe/GitHub 재시도 대응)
        event_id = _extract_event_id(source, request, payload)
        if event_id:
            idempotency_key = f"webhook:idempotency:{source}:{event_id}"
            if not await redis_client.set(idempotency_key, "1", ex=86400, nx=True):
                logger.info("Duplicate %s webhook ignored: %s", source, event_id)
                return {"message": "Webhook already processed."}

        # Increment webhook total counter
        CUSTOMER_WEBHOOK_TOTAL.labels(customer_id=str(customer.id), source=source).inc()

        logger.info(
            f"Received {source} webhook for tenant {tenant_id}. Queuing for processing."
        )
        task = get_task(source)

        # Route tasks to different queues based on source or customer priority
        if source == "github":  # Example of routing
            task.apply_async(
                args=[customer.id, payload],
                queue="high_priority",
            )
        else:
            task.apply_async(args=[customer.id, payload], queue="default")

        return {"message": "Webhook received and queued for processing."}
    except HTTPException as e:
        CUSTOMER_WEBHOOK_ERRORS_TOTAL.labels(
            customer_id=tenant_id, source=source, error_type=e.detail
        ).inc()
        raise e
    except Exception as e:
        CUSTOMER_WEBHOOK_ERRORS_TOTAL.labels(
            customer_id=tenant_id,
            source=source,
            error_type=str(type(e).__name__),
        ).inc()
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        processing_time = time.time() - start_time
        WEBHOOK_PROCESSING_DURATION.labels(
            customer_id=tenant_id, source=source
        ).observe(processing_time)


@app.post(
    "/webhooks/{tenant_id}/events/{event_id}/replay",
    tags=["Events"],
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("5/minute", key_func=get_tenant_id_from_path)
def replay_event(
    tenant_id: str,
    event_id: int,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    """
    Re-queues a specific event for processing for a given tenant.
    Requires authentication via Keycloak.
    """
    logger.info(
        f"User {current_user.get('preferred_username')} "
        f"attempting to replay event_id: {event_id} for tenant: {tenant_id}"
    )

    # 권한 부여 로직 추가 (예: 'admin' 역할만 허용)
    roles = current_user.get("realm_access", {}).get("roles", [])
    if "admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to replay events. Admin role required.",
        )

    # Ensure the tenant exists and is active
    customer = WebhookVerifier(source="any")._get_customer(db, tenant_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Tenant not found or inactive.")

    # Filter by both event_id and customer_id to ensure data isolation
    db_event = WebhookEventRepository().get_for_customer(
        db, event_id=event_id, customer_id=customer.id
    )

    if not db_event:
        logger.warning("Event with id %s not found for tenant %s.", event_id, tenant_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found for this tenant",
        )

    try:
        task = get_task(db_event.source)
        # Pass customer_id to the task for replay
        task.delay(db_event.customer_id, db_event.payload)
    except NotImplementedError:
        logger.error("Replay not implemented for source: %s", db_event.source)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Replay not implemented for source '{db_event.source}'",
        )

    logger.info(
        "Successfully re-queued event_id: %s for tenant %s.", event_id, tenant_id
    )
    return {"message": f"Event {event_id} has been re-queued for processing."}
