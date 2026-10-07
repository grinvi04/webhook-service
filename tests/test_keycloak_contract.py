"""Admin OAuth contract against the installed Keycloak SDK and synthetic HTTP."""

import asyncio
import json
import secrets
import time
from base64 import b64decode, b64encode, urlsafe_b64encode
from urllib.parse import parse_qs, urlparse

import pytest
import redis.asyncio as aioredis
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from jwcrypto import jwk, jwt
from requests import Response

import app.main
from app.config import settings
from app.dependencies import _keycloak_public_key_cache
from keycloak import KeycloakOpenID


class StateRedis:
    def __init__(self):
        self.states = {}

    async def set(self, key, value, ex, nx):
        if key in self.states:
            return False
        self.states[key] = value
        return True

    async def getdel(self, key):
        return self.states.pop(key, None)


def _response(status_code, payload):
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode()
    return response


def _session(client):
    cookie = client.cookies.get("session")
    if not cookie:
        return {}
    return json.loads(b64decode(TimestampSigner(settings.session_secret).unsign(cookie)))


def _set_session(client, values):
    encoded = b64encode(json.dumps(values).encode())
    client.cookies.clear()
    client.cookies.set(
        "session",
        TimestampSigner(settings.session_secret).sign(encoded).decode(),
        domain="testserver.local",
        path="/",
    )


@pytest.fixture
def oauth(mocker):
    keycloak = KeycloakOpenID(
        server_url="https://qa-keycloak.invalid/", realm_name="qa-realm", client_id="qa-client"
    )
    mocker.patch.object(app.main.app.state, "keycloak_openid", keycloak)
    mocker.patch.object(app.main.app.state, "redis", StateRedis(), create=True)
    get = mocker.patch.object(
        keycloak.connection._s,
        "get",
        return_value=_response(
            200,
            {
                "authorization_endpoint": "https://qa-keycloak.invalid/realms/qa-realm/protocol/openid-connect/auth"
            },
        ),
    )
    post = mocker.patch.object(
        keycloak.connection._s,
        "post",
        return_value=_response(200, {"access_token": "synthetic-token"}),
    )
    return TestClient(app.main.app, raise_server_exceptions=False), get, post


def _login(client):
    response = client.get("/admin/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["redirect_uri"] == ["http://testserver/admin/oauth2-callback"]
    state = query["state"][0]
    assert len(state) >= 32
    assert state == _session(client)["oauth_state"]
    return state


@pytest.mark.parametrize(
    "root,expected",
    [
        ("https://qa-keycloak.invalid", "https://qa-keycloak.invalid/"),
        ("https://qa-keycloak.invalid/", "https://qa-keycloak.invalid/"),
        ("https://qa-keycloak.invalid/auth", "https://qa-keycloak.invalid/auth/"),
    ],
)
def test_keycloak_root_url_normalizes_trailing_slash(root, expected):
    assert app.main._keycloak_server_url(root) == expected


def test_application_keycloak_client_uses_one_realm_path(mocker):
    keycloak = app.main.keycloak_openid
    expected = f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}"
    get = mocker.patch.object(
        keycloak.connection._s, "get", return_value=_response(200, {"public_key": "synthetic"})
    )
    assert keycloak.public_key() == "synthetic"
    assert get.call_args.args[0] == expected
    get.return_value = _response(200, {"keys": []})
    assert keycloak.certs() == {"keys": []}
    assert get.call_args.args[0] == f"{expected}/protocol/openid-connect/certs"


def test_login_callback_real_sdk_and_old_cookie_replay_denied(oauth):
    client, get, post = oauth
    state = _login(client)
    old_cookie = client.cookies["session"]
    assert (
        get.call_args.args[0]
        == "https://qa-keycloak.invalid/realms/qa-realm/.well-known/openid-configuration"
    )
    callback = client.get(
        "/admin/oauth2-callback",
        params={"code": "synthetic-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code in (302, 307)
    assert callback.headers["location"] == "/admin"
    assert (
        post.call_args.args[0]
        == "https://qa-keycloak.invalid/realms/qa-realm/protocol/openid-connect/token"
    )
    assert post.call_args.kwargs["data"]["code"] == "synthetic-code"
    assert post.call_args.kwargs["data"]["grant_type"] == "authorization_code"
    assert (
        post.call_args.kwargs["data"]["redirect_uri"] == "http://testserver/admin/oauth2-callback"
    )
    assert _session(client) == {"token": "synthetic-token"}

    replay_browser = TestClient(app.main.app, raise_server_exceptions=False)
    replay_browser.cookies.set("session", old_cookie, domain="testserver.local", path="/")
    replay = replay_browser.get(
        "/admin/oauth2-callback",
        params={"code": "synthetic-code", "state": state},
        follow_redirects=False,
    )
    assert replay.status_code == 401
    assert post.call_count == 1
    assert "token" not in _session(replay_browser)


def test_missing_mismatched_other_browser_and_expired_state_denied(oauth):
    client, _, post = oauth
    state = _login(client)
    other_browser = TestClient(app.main.app, raise_server_exceptions=False)
    for browser, query in (
        (client, {"code": "synthetic-code"}),
        (other_browser, {"code": "synthetic-code", "state": state}),
        (client, {"code": "synthetic-code", "state": "wrong-state"}),
    ):
        result = browser.get("/admin/oauth2-callback", params=query, follow_redirects=False)
        assert result.status_code in (401, 422)
        assert "token" not in _session(browser)
    post.assert_not_called()

    state = _login(client)
    signed = _session(client)
    signed["oauth_state_issued_at"] = time.time() - 301
    _set_session(client, signed)
    expired = client.get(
        "/admin/oauth2-callback",
        params={"code": "synthetic-code", "state": state},
        follow_redirects=False,
    )
    assert expired.status_code == 401
    post.assert_not_called()
    state = _login(client)
    signed = _session(client)
    signed["oauth_state_issued_at"] = time.time() + 60
    _set_session(client, signed)
    future = client.get(
        "/admin/oauth2-callback",
        params={"code": "synthetic-code", "state": state},
        follow_redirects=False,
    )
    assert future.status_code == 401
    post.assert_not_called()


def test_provider_error_consumes_state_without_authentication(oauth):
    client, _, post = oauth
    post.return_value = _response(401, {"error": "invalid_grant"})
    missing_code = client.get("/admin/oauth2-callback", follow_redirects=False)
    assert missing_code.status_code == 422
    post.assert_not_called()
    _set_session(client, {"token": "previous-synthetic-token"})
    state = _login(client)
    assert "token" not in _session(client)
    old_cookie = client.cookies["session"]
    rejected = client.get(
        "/admin/oauth2-callback",
        params={"code": "bad-code", "state": state},
        follow_redirects=False,
    )
    assert rejected.status_code >= 400
    assert post.call_count == 1
    assert "token" not in _session(client)
    client.cookies.clear()
    client.cookies.set("session", old_cookie, domain="testserver.local", path="/")
    replay = client.get(
        "/admin/oauth2-callback",
        params={"code": "bad-code", "state": state},
        follow_redirects=False,
    )
    assert replay.status_code == 401
    assert post.call_count == 1


def test_redis_failure_stops_code_exchange(oauth, mocker):
    client, _, post = oauth
    state = _login(client)
    mocker.patch.object(
        app.main.app.state.redis, "getdel", side_effect=ConnectionError("synthetic")
    )
    result = client.get(
        "/admin/oauth2-callback",
        params={"code": "synthetic-code", "state": state},
        follow_redirects=False,
    )
    assert result.status_code == 500
    post.assert_not_called()
    assert "token" not in _session(client)


@pytest.fixture
def signed_realm_token(mocker):
    private = jwk.JWK.generate(kty="RSA", size=2048)
    public_pem = private.export_to_pem(private_key=False, password=None).decode()
    public_body = "".join(public_pem.splitlines()[1:-1])
    keycloak = KeycloakOpenID(
        server_url="https://qa-keycloak.invalid/", realm_name="qa-realm", client_id="qa-client"
    )
    mocker.patch.object(app.main.app.state, "keycloak_openid", keycloak)
    get = mocker.patch.object(
        keycloak.connection._s,
        "get",
        return_value=_response(200, {"public_key": public_body}),
    )
    _keycloak_public_key_cache.update({"key": None, "expires_at": 0.0})

    def make_token(claims, signing_key=None):
        payload = {"sub": "qa", "exp": int(time.time()) + 300, **claims}
        if payload["exp"] is None:
            del payload["exp"]
        token = jwt.JWT(
            header={"alg": "RS256"},
            claims=payload,
        )
        token.make_signed_token(signing_key or private)
        return token.serialize()

    return make_token, get


def _unsigned_token(claims):
    def part(value):
        return urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}."


@pytest.mark.parametrize(
    "case",
    ["expired-10", "expired-120", "missing-exp", "wrong-key", "hs256", "none"],
)
def test_sdk_migration_denies_invalid_token_in_ui_and_replay(mocker, signed_realm_token, case):
    make_token, _ = signed_realm_token
    claims = {"realm_access": {"roles": ["admin"]}}
    if case == "expired-10":
        token = make_token({**claims, "exp": int(time.time()) - 10})
    elif case == "expired-120":
        token = make_token({**claims, "exp": int(time.time()) - 120})
    elif case == "missing-exp":
        token = make_token({**claims, "exp": None})
    elif case == "wrong-key":
        token = make_token(claims, jwk.JWK.generate(kty="RSA", size=2048))
    elif case == "hs256":
        signed = jwt.JWT(header={"alg": "HS256"}, claims={**claims, "exp": int(time.time()) + 300})
        signed.make_signed_token(
            jwk.JWK(
                kty="oct",
                k=urlsafe_b64encode(b"synthetic-test-secret-32-bytes-long!").decode().rstrip("="),
            )
        )
        token = signed.serialize()
    else:
        token = _unsigned_token({**claims, "exp": int(time.time()) + 300})

    client = TestClient(app.main.app, raise_server_exceptions=False)
    _set_session(client, {"token": token})
    connect = mocker.patch.object(app.main.database.engine, "connect")
    dashboard = client.get("/admin/webhook-event/list", follow_redirects=False)
    assert dashboard.status_code in (302, 303, 307, 401, 403)
    assert "token" not in _session(client)
    connect.assert_not_called()

    customer = mocker.patch("app.main.WebhookVerifier._get_customer", return_value=None)
    app.main.app.dependency_overrides[app.main.database.get_db] = lambda: mocker.Mock()
    try:
        replay = client.post(
            "/webhooks/qa-migration/events/1/replay",
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=False,
        )
        assert replay.status_code == 401
        customer.assert_not_called()
    finally:
        app.main.app.dependency_overrides.clear()


def test_real_redis_state_marker_has_one_atomic_winner(isolated_service_db):
    async def exercise():
        redis = aioredis.from_url(settings.redis_url)
        key = f"admin:oauth-state:{secrets.token_urlsafe(32)}"
        try:
            assert await redis.set(key, "1", ex=300, nx=True)
            results = await asyncio.gather(redis.getdel(key), redis.getdel(key))
            assert sorted(results, key=lambda value: value is None) == [b"1", None]
            assert await redis.get(key) is None
        finally:
            await redis.delete(key)
            await redis.aclose()

    asyncio.run(exercise())


def test_signed_admin_role_allows_dashboard(signed_realm_token, mocker):
    make_token, get = signed_realm_token
    client = TestClient(app.main.app, raise_server_exceptions=False)
    token = make_token({"realm_access": {"roles": ["admin", "user"]}})
    _set_session(client, {"token": token})
    assert "session=" in client.build_request("GET", "/admin/").headers.get("cookie", "")
    from app.admin import authentication_backend

    seen = []
    original = authentication_backend.authenticate

    async def capture(request):
        seen.append(dict(request.session))
        return await original(request)

    mocker.patch.object(authentication_backend, "authenticate", side_effect=capture)
    result = client.get("/admin", follow_redirects=False)
    assert result.status_code == 307
    assert result.headers["location"] == "http://testserver/admin/"
    dashboard = client.get("/admin/", follow_redirects=False)
    assert seen and seen[0].get("token") == token
    assert get.call_count == 1
    assert dashboard.status_code == 200
    assert get.call_args.args[0] == "https://qa-keycloak.invalid/realms/qa-realm"


@pytest.mark.parametrize(
    "claims",
    [
        {"realm_access": {"roles": ["user"]}},
        {"realm_access": {"roles": ["superadmin"]}},
        {"realm_access": {"roles": [123, {"name": "admin"}]}},
        {},
        {"realm_access": {"roles": "admin"}},
        {"realm_access": ["admin"]},
    ],
)
def test_signed_nonadmin_or_malformed_roles_denied_without_db(mocker, signed_realm_token, claims):
    make_token, _ = signed_realm_token
    client = TestClient(app.main.app, raise_server_exceptions=False)
    _set_session(client, {"token": make_token(claims)})
    connect = mocker.patch.object(app.main.database.engine, "connect")
    result = client.get("/admin/webhook-event/list", follow_redirects=False)
    assert result.status_code in (302, 303, 307, 401, 403)
    assert "token" not in _session(client)
    connect.assert_not_called()


@pytest.mark.parametrize("invalid", ["wrong-signature", "expired", "hs256"])
def test_invalid_or_expired_signature_denied_without_db(mocker, signed_realm_token, invalid):
    make_token, _ = signed_realm_token
    if invalid == "wrong-signature":
        token = make_token(
            {"realm_access": {"roles": ["admin"]}}, jwk.JWK.generate(kty="RSA", size=2048)
        )
    else:
        if invalid == "expired":
            token = make_token({"realm_access": {"roles": ["admin"]}, "exp": int(time.time()) - 10})
        else:
            token = jwt.JWT(
                header={"alg": "HS256"},
                claims={"realm_access": {"roles": ["admin"]}, "exp": int(time.time()) + 300},
            )
            token.make_signed_token(
                jwk.JWK(
                    kty="oct",
                    k=urlsafe_b64encode(b"synthetic-test-secret-32-bytes-long!")
                    .decode()
                    .rstrip("="),
                )
            )
            token = token.serialize()
    client = TestClient(app.main.app, raise_server_exceptions=False)
    _set_session(client, {"token": token})
    connect = mocker.patch.object(app.main.database.engine, "connect")
    result = client.get("/admin/webhook-event/list", follow_redirects=False)
    assert result.status_code in (302, 303, 307, 401, 403)
    assert "token" not in _session(client)
    connect.assert_not_called()


@pytest.mark.parametrize(
    "case,expected_status,queries",
    [
        ("admin", 404, 1),
        ("nonadmin", 403, 0),
        ("string-role", 403, 0),
        ("malformed-claims", 403, 0),
        ("invalid-signature", 401, 0),
        ("expired", 401, 0),
    ],
)
def test_replay_uses_same_real_sdk_signature_and_roles(
    mocker, signed_realm_token, case, expected_status, queries
):
    make_token, _ = signed_realm_token
    claims = {"realm_access": {"roles": ["admin" if case != "nonadmin" else "user"]}}
    if case == "string-role":
        claims = {"realm_access": {"roles": "admin"}}
    elif case == "malformed-claims":
        claims = {"realm_access": ["admin"]}
    if case == "invalid-signature":
        token = make_token(claims, jwk.JWK.generate(kty="RSA", size=2048))
    elif case == "expired":
        token = make_token({**claims, "exp": int(time.time()) - 10})
    else:
        token = make_token(claims)
    customer = mocker.patch("app.main.WebhookVerifier._get_customer", return_value=None)
    app.main.app.dependency_overrides[app.main.database.get_db] = lambda: mocker.Mock()
    try:
        client = TestClient(app.main.app, raise_server_exceptions=False)
        result = client.post(
            f"/webhooks/qa-{case}/events/1/replay",
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=False,
        )
        assert result.status_code == expected_status
        assert customer.call_count == queries
    finally:
        app.main.app.dependency_overrides.clear()
