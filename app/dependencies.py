import hashlib
import hmac
import logging
from typing import Any

import redis.asyncio as aioredis
import stripe
from fastapi import HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .models.customer import Customer

logger = logging.getLogger(__name__)


def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


def get_tenant_id_from_path(request: Request) -> str | None:
    """
    Extracts the tenant_id from the request path if available.
    """
    return request.path_params.get("tenant_id")


def rate_limit_key_func(request: Request) -> str:
    """
    Determines the key for rate limiting.
    - If tenant_id is present in the path, use it.
    - Otherwise, fall back to the client's IP address.
    """
    tenant_id = get_tenant_id_from_path(request)
    if tenant_id:
        return tenant_id
    return get_remote_address(request)


# Initialize the rate limiter
limiter = Limiter(key_func=rate_limit_key_func, default_limits=["100/minute"])


async def get_current_user(request: Request) -> dict[str, Any]:
    """
    Keycloak 토큰을 검증하고 사용자 정보를 반환하는 의존성 함수.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token_type, access_token = auth_header.split(" ")
        if token_type.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication scheme",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # app.state에 저장된 keycloak_openid 객체 사용
        keycloak_openid = request.app.state.keycloak_openid

        # 토큰 검증 및 디코딩
        user_info = keycloak_openid.decode_token(
            access_token,
            key=keycloak_openid.public_key(),  # Keycloak에서 공개 키를 가져와야 합니다.
            options={"verify_signature": True, "verify_aud": False, "exp": True},
        )

        # 필요한 경우 사용자 역할(role) 검증 로직 추가
        # roles = user_info.get("realm_access", {}).get("roles", [])
        # if "admin" not in roles:
        #     raise HTTPException(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         detail="Not enough permissions"
        #     )

        return user_info

    except Exception as e:
        logger.error("Keycloak token validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


class WebhookVerifier:
    """
    A generic webhook signature verifier that can be configured for different providers.
    It also ensures that the provided tenant_id is valid.
    """

    def __init__(self, source: str):
        self.source = source

    async def __call__(self, request: Request, tenant_id: str, db: AsyncSession):
        customer = await self._get_customer_async(db, tenant_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        body = await request.body()
        secret = customer.webhook_secret

        if self.source == "github":
            await self._verify_github(request, body, secret)
        elif self.source == "stripe":
            await self._verify_stripe(request, body, secret)
        else:
            logger.error("Verifier for source '%s' is not implemented.", self.source)
            raise HTTPException(
                status_code=501,
                detail=f"Verifier for source '{self.source}' is not implemented.",
            )
        return customer

    def _get_customer(self, db: Session, tenant_id: str) -> Customer | None:
        customer = db.query(Customer).filter(Customer.tenant_id == tenant_id).first()
        if customer and not customer.is_active:
            raise HTTPException(status_code=403, detail="Tenant is inactive.")
        return customer

    async def _get_customer_async(
        self, db: AsyncSession, tenant_id: str
    ) -> Customer | None:
        result = await db.execute(
            select(Customer).where(Customer.tenant_id == tenant_id)
        )
        customer = result.scalar_one_or_none()
        if customer and not customer.is_active:
            raise HTTPException(status_code=403, detail="Tenant is inactive.")
        return customer

    async def _verify_github(self, request: Request, body: bytes, secret: str):
        secret_bytes = secret.encode("utf-8")
        signature_header = request.headers.get("x-hub-signature-256")

        if not signature_header:
            raise HTTPException(
                status_code=400, detail="X-Hub-Signature-256 header is missing."
            )

        signature = hmac.new(secret_bytes, body, hashlib.sha256).hexdigest()
        expected_signature = f"sha256={signature}"

        if not hmac.compare_digest(expected_signature, signature_header):
            raise HTTPException(status_code=401, detail="Invalid GitHub signature.")

    async def _verify_stripe(self, request: Request, body: bytes, secret: str):
        signature_header = request.headers.get("stripe-signature")
        if not signature_header:
            raise HTTPException(
                status_code=400, detail="Stripe-Signature header is missing."
            )

        try:
            # Use the official Stripe library to construct and verify the event
            stripe.Webhook.construct_event(
                payload=body, sig_header=signature_header, secret=secret
            )
        except stripe.error.SignatureVerificationError as e:
            # The signature is invalid
            raise HTTPException(
                status_code=401, detail="Invalid Stripe signature."
            ) from e
