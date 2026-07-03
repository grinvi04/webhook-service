"""
Real-cryptography tests for _verify_github, _verify_stripe, get_current_user.

Issue #58: 실 경로 테스트 부재 — 서명 생성·검증을 실제 알고리즘으로 수행해
mock 치환으로 숨겨질 수 없는 회귀를 잡는다.
"""

import hashlib
import hmac
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.dependencies import WebhookVerifier, get_current_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(headers: dict[str, str], app_state: Any | None = None) -> MagicMock:
    req = MagicMock()
    req.headers = headers
    if app_state is not None:
        req.app.state = app_state
    return req


def _github_sig(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _stripe_sig_header(body: bytes, secret: str) -> str:
    ts = str(int(time.time()))
    signed = f"{ts}.{body.decode('utf-8')}"
    digest = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


# ---------------------------------------------------------------------------
# _verify_github
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVerifyGithub:
    @pytest.fixture
    def verifier(self):
        return WebhookVerifier(source="github")

    async def test_valid_signature_passes(self, verifier):
        secret = "mysecret"
        body = b'{"action":"opened"}'
        sig = _github_sig(body, secret)
        req = _make_request({"x-hub-signature-256": sig})

        await verifier._verify_github(req, body, secret)  # must not raise

    async def test_invalid_signature_raises_401(self, verifier):
        secret = "mysecret"
        body = b'{"action":"opened"}'
        req = _make_request({"x-hub-signature-256": "sha256=badhash"})

        with pytest.raises(HTTPException) as exc_info:
            await verifier._verify_github(req, body, secret)

        assert exc_info.value.status_code == 401

    async def test_tampered_body_raises_401(self, verifier):
        secret = "mysecret"
        original = b'{"action":"opened"}'
        sig = _github_sig(original, secret)
        tampered = b'{"action":"deleted"}'
        req = _make_request({"x-hub-signature-256": sig})

        with pytest.raises(HTTPException) as exc_info:
            await verifier._verify_github(req, tampered, secret)

        assert exc_info.value.status_code == 401

    async def test_missing_header_raises_400(self, verifier):
        req = _make_request({})

        with pytest.raises(HTTPException) as exc_info:
            await verifier._verify_github(req, b"body", "secret")

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# _verify_stripe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVerifyStripe:
    @pytest.fixture
    def verifier(self):
        return WebhookVerifier(source="stripe")

    async def test_valid_signature_passes(self, verifier):
        secret = "whsec_testsecret"
        body = b'{"type":"checkout.session.completed"}'
        sig_header = _stripe_sig_header(body, secret)
        req = _make_request({"stripe-signature": sig_header})

        await verifier._verify_stripe(req, body, secret)  # must not raise

    async def test_invalid_signature_raises_401(self, verifier):
        secret = "whsec_testsecret"
        body = b'{"type":"checkout.session.completed"}'
        bad_sig = f"t={int(time.time())},v1=badhash"
        req = _make_request({"stripe-signature": bad_sig})

        with pytest.raises(HTTPException) as exc_info:
            await verifier._verify_stripe(req, body, secret)

        assert exc_info.value.status_code == 401

    async def test_wrong_secret_raises_401(self, verifier):
        body = b'{"type":"payment_intent.succeeded"}'
        sig_header = _stripe_sig_header(body, "correct_secret")
        req = _make_request({"stripe-signature": sig_header})

        with pytest.raises(HTTPException) as exc_info:
            await verifier._verify_stripe(req, body, "wrong_secret")

        assert exc_info.value.status_code == 401

    async def test_missing_header_raises_400(self, verifier):
        req = _make_request({})

        with pytest.raises(HTTPException) as exc_info:
            await verifier._verify_stripe(req, b"body", "secret")

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetCurrentUser:
    async def test_missing_auth_header_raises_401(self):
        req = _make_request({})

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(req)

        assert exc_info.value.status_code == 401
        assert "missing" in exc_info.value.detail.lower()

    async def test_non_bearer_scheme_raises_401(self):
        req = _make_request({"Authorization": "Basic dXNlcjpwYXNz"})

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(req)

        assert exc_info.value.status_code == 401

    async def test_invalid_token_raises_401(self):
        mock_kc = MagicMock()
        mock_kc.public_key.return_value = "pubkey"
        mock_kc.decode_token.side_effect = Exception("token expired")
        state = MagicMock()
        state.keycloak_openid = mock_kc
        req = _make_request({"Authorization": "Bearer invalidtoken"}, app_state=state)

        _kc_patch = patch(
            "app.dependencies._get_keycloak_public_key",
            new=AsyncMock(return_value="pubkey"),
        )
        with _kc_patch:
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(req)

        assert exc_info.value.status_code == 401

    async def test_valid_token_returns_user_info(self):
        expected = {"sub": "user-123", "email": "user@example.com"}
        mock_kc = MagicMock()
        mock_kc.decode_token.return_value = expected
        state = MagicMock()
        state.keycloak_openid = mock_kc
        req = _make_request({"Authorization": "Bearer validtoken"}, app_state=state)

        _kc_patch = patch(
            "app.dependencies._get_keycloak_public_key",
            new=AsyncMock(return_value="pubkey"),
        )
        with _kc_patch:
            result = await get_current_user(req)

        assert result == expected
        mock_kc.decode_token.assert_called_once_with(
            "validtoken",
            key="pubkey",
            options={"verify_signature": True, "verify_aud": False, "exp": True},
        )
