import base64
import json
import time

from fastapi import Request, Response
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.responses import RedirectResponse

from .config import settings
from .models.webhook_event import WebhookEvent


class KeycloakAuth(AuthenticationBackend):
    async def login(self, request: Request) -> Response:  # type: ignore[override]
        keycloak_openid = request.app.state.keycloak_openid
        auth_url = keycloak_openid.auth_url(
            redirect_uri=request.url_for("admin:oauth2_callback"),
            scope="openid profile email",
        )
        return RedirectResponse(auth_url)

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        token = request.session.get("token")
        if not token:
            return False
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            if payload.get("exp", 0) < time.time():
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
    can_delete = True
    name = "Webhook Event"
    name_plural = "Webhook Events"
    icon = "fa-solid fa-paper-plane"


def setup_admin(app, engine):
    admin = Admin(app, engine, authentication_backend=authentication_backend)
    admin.add_view(WebhookEventAdmin)

    @app.get("/admin/oauth2-callback")
    async def oauth2_callback(request: Request, code: str):
        # Keycloak으로부터 받은 인증 코드를 사용하여 토큰 교환
        keycloak_openid = request.app.state.keycloak_openid
        token = keycloak_openid.exchange_code_for_token(
            code=code,
            redirect_uri=request.url_for("admin:oauth2_callback"),
        )
        # 토큰을 세션에 저장
        request.session.update({"token": token["access_token"]})
        return RedirectResponse(url="/admin")
