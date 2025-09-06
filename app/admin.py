from sqladmin import Admin, ModelView
from .models.webhook_event import WebhookEvent

class WebhookEventAdmin(ModelView, model=WebhookEvent):
    column_list = [WebhookEvent.id, WebhookEvent.source, WebhookEvent.received_at]
    column_searchable_list = [WebhookEvent.source]
    column_sortable_list = [WebhookEvent.id, WebhookEvent.received_at]
    column_details_exclude_list = [WebhookEvent.payload] # Payload is too large for list view
    can_create = False
    can_edit = False
    can_delete = True
    name = "Webhook Event"
    name_plural = "Webhook Events"
    icon = "fa-solid fa-paper-plane"

def setup_admin(app, engine):
    admin = Admin(app, engine)
    admin.add_view(WebhookEventAdmin)
