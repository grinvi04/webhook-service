import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from keycloak import KeycloakOpenID

from . import admin, database
from .config import settings
from .dependencies import (
    WebhookVerifier,
    get_current_user,
    get_tenant_id_from_path,
    limiter,
)
from .logging_config import setup_logging
from .metrics import (
    CUSTOMER_WEBHOOK_ERRORS_TOTAL,
    CUSTOMER_WEBHOOK_TOTAL,
    WEBHOOK_PROCESSING_DURATION,
)
from .models.webhook_event import WebhookEvent
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
    yield


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


# Keycloak 인증 미들웨어 (예시, 실제 구현은 더 복잡할 수 있음)
@app.middleware("http")
async def add_keycloak_auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/admin"):
        # 여기에 Keycloak 토큰 검증 로직 추가
        # 예: request.headers.get("Authorization")에서 토큰 추출 및 검증
        # 유효하지 않은 경우 HTTPException(status_code=401) 발생
        # 이 부분은 실제 Keycloak 연동 로직에 따라 구현해야 합니다.
        # 현재는 단순히 통과시키거나, 더미 인증을 수행할 수 있습니다.
        pass
    response = await call_next(request)
    return response


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
    db: Session = Depends(database.get_db),
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
    db_event = (
        db.query(WebhookEvent)
        .filter(WebhookEvent.id == event_id, WebhookEvent.customer_id == customer.id)
        .first()
    )

    if not db_event:
        logger.warning(f"Event with id {event_id} not found for tenant {tenant_id}.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found for this tenant",
        )

    try:
        task = get_task(db_event.source)
        # Pass customer_id to the task for replay
        task.delay(db_event.customer_id, db_event.payload)
    except NotImplementedError:
        logger.error(f"Replay not implemented for source: {db_event.source}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Replay not implemented for source '{db_event.source}'",
        )

    logger.info(f"Successfully re-queued event_id: {event_id} for tenant {tenant_id}.")
    return {"message": f"Event {event_id} has been re-queued for processing."}
