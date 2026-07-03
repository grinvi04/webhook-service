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


async def test_github_valid_signature_passes():
    verifier = WebhookVerifier(source="github")
    secret = "mysecret"
    body = b'{"action":"opened"}'
    sig = _github_sig(body, secret)
    req = _make_request({"x-hub-signature-256": sig})

    await verifier._verify_github(req, body, secret)  # must not raise


async def test_github_invalid_signature_raises_401():
    verifier = WebhookVerifier(source="github")
    body = b'{"action":"opened"}'
    req = _make_request({"x-hub-signature-256": "sha256=badhash"})

    with pytest.raises(HTTPException) as exc_info:
        await verifier._verify_github(req, body, "mysecret")

    assert exc_info.value.status_code == 401


async def test_github_tampered_body_raises_401():
    verifier = WebhookVerifier(source="github")
    secret = "mysecret"
    original = b'{"action":"opened"}'
    sig = _github_sig(original, secret)
    tampered = b'{"action":"deleted"}'
    req = _make_request({"x-hub-signature-256": sig})

    with pytest.raises(HTTPException) as exc_info:
        await verifier._verify_github(req, tampered, secret)

    assert exc_info.value.status_code == 401


async def test_github_missing_header_raises_400():
    verifier = WebhookVerifier(source="github")
    req = _make_request({})

    with pytest.raises(HTTPException) as exc_info:
        await verifier._verify_github(req, b"body", "secret")

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# _verify_stripe
# ---------------------------------------------------------------------------


async def test_stripe_valid_signature_passes():
    verifier = WebhookVerifier(source="stripe")
    secret = "whsec_testsecret"
    body = b'{"type":"checkout.session.completed"}'
    sig_header = _stripe_sig_header(body, secret)
    req = _make_request({"stripe-signature": sig_header})

    await verifier._verify_stripe(req, body, secret)  # must not raise


async def test_stripe_invalid_signature_raises_401():
    verifier = WebhookVerifier(source="stripe")
    body = b'{"type":"checkout.session.completed"}'
    bad_sig = f"t={int(time.time())},v1=badhash"
    req = _make_request({"stripe-signature": bad_sig})

    with pytest.raises(HTTPException) as exc_info:
        await verifier._verify_stripe(req, body, "whsec_testsecret")

    assert exc_info.value.status_code == 401


async def test_stripe_wrong_secret_raises_401():
    verifier = WebhookVerifier(source="stripe")
    body = b'{"type":"payment_intent.succeeded"}'
    sig_header = _stripe_sig_header(body, "correct_secret")
    req = _make_request({"stripe-signature": sig_header})

    with pytest.raises(HTTPException) as exc_info:
        await verifier._verify_stripe(req, body, "wrong_secret")

    assert exc_info.value.status_code == 401


async def test_stripe_missing_header_raises_400():
    verifier = WebhookVerifier(source="stripe")
    req = _make_request({})

    with pytest.raises(HTTPException) as exc_info:
        await verifier._verify_stripe(req, b"body", "secret")

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

_KC_PATCH = "app.dependencies._get_keycloak_public_key"


async def test_auth_missing_header_raises_401():
    req = _make_request({})

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(req)

    assert exc_info.value.status_code == 401
    assert "missing" in exc_info.value.detail.lower()


async def test_auth_non_bearer_scheme_raises_401():
    req = _make_request({"Authorization": "Basic dXNlcjpwYXNz"})

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(req)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid authentication scheme"


async def test_auth_single_word_header_raises_401():
    req = _make_request({"Authorization": "Bearer"})

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(req)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid authentication scheme"


async def test_auth_invalid_token_raises_401():
    mock_kc = MagicMock()
    mock_kc.decode_token.side_effect = Exception("token expired")
    state = MagicMock()
    state.keycloak_openid = mock_kc
    req = _make_request({"Authorization": "Bearer invalidtoken"}, app_state=state)

    with patch(_KC_PATCH, new=AsyncMock(return_value="pubkey")):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(req)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Could not validate credentials"


async def test_auth_valid_token_returns_user_info():
    expected = {"sub": "user-123", "email": "user@example.com"}
    mock_kc = MagicMock()
    mock_kc.decode_token.return_value = expected
    state = MagicMock()
    state.keycloak_openid = mock_kc
    req = _make_request({"Authorization": "Bearer validtoken"}, app_state=state)

    with patch(_KC_PATCH, new=AsyncMock(return_value="pubkey")):
        result = await get_current_user(req)

    assert result == expected
    mock_kc.decode_token.assert_called_once_with(
        "validtoken",
        key="pubkey",
        options={"verify_signature": True, "verify_aud": False, "exp": True},
    )
