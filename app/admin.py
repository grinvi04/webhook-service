import secrets
import time

from fastapi import FastAPI, HTTPException, Request, Response
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.responses import RedirectResponse

from .config import settings
from .dependencies import _decode_keycloak_token
from .models.webhook_event import WebhookEvent

_OAUTH_STATE_MAX_AGE_SECONDS = 300


class KeycloakAuth(AuthenticationBackend):
    root_app: FastAPI

    async def login(self, request: Request) -> Response:  # type: ignore[override]
        request.session.pop("token", None)
        state = secrets.token_urlsafe(32)
        keycloak_openid = request.app.state.keycloak_openid
        auth_url = keycloak_openid.auth_url(
            redirect_uri=request.url_for("oauth2_callback"),
            scope="openid profile email",
            state=state,
        )
        reserved = await request.app.state.redis.set(
            f"admin:oauth-state:{state}", "1", ex=_OAUTH_STATE_MAX_AGE_SECONDS, nx=True
        )
        if not reserved:
            raise HTTPException(status_code=503, detail="Login unavailable")
        request.session["oauth_state"] = state
        request.session["oauth_state_issued_at"] = time.time()
        return RedirectResponse(auth_url.strip())

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        token = request.session.get("token")
        if not token:
            return False
        try:
            keycloak_openid = self.root_app.state.keycloak_openid
            claims = await _decode_keycloak_token(keycloak_openid, token)
            realm_access = claims.get("realm_access")
            roles = realm_access.get("roles") if isinstance(realm_access, dict) else None
            if not isinstance(roles, list) or "admin" not in roles:
                request.session.clear()
                return False
            return True
        except Exception:
            request.session.clear()
            return False


authentication_backend = KeycloakAuth(secret_key=settings.session_secret)


class WebhookEventAdmin(ModelView, model=WebhookEvent):
    column_list = ["id", "source", "received_at"]
    column_searchable_list = ["source"]
    column_sortable_list = ["id", "received_at"]
    # Payload is too large for list view
    column_details_exclude_list = ["payload"]
    can_create = False
    can_edit = False
    # 하드삭제 금지 — 감사이력(웹훅 수신 기록) 영구삭제 방지 (M4)
    can_delete = False
    name = "Webhook Event"
    name_plural = "Webhook Events"
    icon = "fa-solid fa-paper-plane"


def setup_admin(app, engine):
    authentication_backend.root_app = app

    @app.get("/admin/login")
    async def oauth2_login(request: Request):
        return await authentication_backend.login(request)

    @app.get("/admin/oauth2-callback")
    async def oauth2_callback(request: Request, code: str, state: str):
        expected = request.session.pop("oauth_state", None)
        issued_at = request.session.pop("oauth_state_issued_at", None)
        if not isinstance(expected, str) or not isinstance(issued_at, (int, float)):
            raise HTTPException(status_code=401, detail="Invalid login state")
        marker = await request.app.state.redis.getdel(f"admin:oauth-state:{expected}")
        age = time.time() - issued_at
        if (
            not marker
            or not 0 <= age <= _OAUTH_STATE_MAX_AGE_SECONDS
            or not secrets.compare_digest(expected, state)
        ):
            raise HTTPException(status_code=401, detail="Invalid login state")
        keycloak_openid = request.app.state.keycloak_openid
        token = keycloak_openid.token(
            code=code,
            grant_type="authorization_code",
            redirect_uri=request.url_for("oauth2_callback"),
        )
        request.session["token"] = token["access_token"]
        return RedirectResponse(url="/admin")

    admin = Admin(app, engine, authentication_backend=authentication_backend)
    admin.add_view(WebhookEventAdmin)
