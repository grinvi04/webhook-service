from celery import Celery
from kombu import Exchange, Queue

from .config import settings

celery = Celery(
    __name__,
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.services.webhook_handler"],
)

# Define exchanges
default_exchange = Exchange("default", type="direct")
priority_exchange = Exchange("priority", type="direct")
dead_letter_exchange = Exchange("dead_letters", type="direct")

# Define queues
celery.conf.task_queues = (
    Queue(
        "default",
        default_exchange,
        routing_key="default",
    ),
    Queue(
        "high_priority",
        priority_exchange,
        routing_key="high_priority",
    ),
    Queue(
        "dead_letters",
        dead_letter_exchange,
        routing_key="dead_letters",
    ),
)
celery.conf.task_default_queue = "default"
celery.conf.task_default_exchange = "default"
celery.conf.task_default_routing_key = "default"


celery.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
