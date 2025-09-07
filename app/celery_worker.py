from celery import Celery

from .config import settings

celery = Celery(
    __name__,
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.services.webhook_handler"],  # Add this line
)

celery.conf.update(
    task_track_started=True,
)
