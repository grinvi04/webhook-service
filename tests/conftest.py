import os
import sys
from urllib.parse import urlparse

import pytest
from pydantic_settings import BaseSettings

os.environ.setdefault("SESSION_SECRET", "test-secret-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-github-webhook-secret")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "test-stripe-webhook-secret")

if "app.config" in sys.modules:
    raise RuntimeError("test settings bootstrap must precede app.config import")

_base_settings_init = BaseSettings.__init__


def _qa_settings_init(self, *args, **kwargs):
    if kwargs.get("_env_file") is not None:
        raise AssertionError("test settings cannot load a dotenv file")
    kwargs["_env_file"] = None
    _base_settings_init(self, *args, **kwargs)


BaseSettings.__init__ = _qa_settings_init


def _assert_isolated_service_targets():
    """Reject every effective service destination before a live test can connect."""
    for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR"):
        if name in os.environ:
            raise AssertionError(f"{name} must be unset for isolated QA tests")

    from app.celery_worker import celery
    from app.config import settings
    from app.database import async_engine, engine

    ci = os.environ.get("GITHUB_ACTIONS") == "true"
    pg_port, pg_db, redis_port = (5432, "test_db", 6379) if ci else (55441, "webhook_qa", 56381)
    destinations = {
        "DATABASE_URL": (settings.database_url, "postgresql+psycopg2", pg_port, f"/{pg_db}"),
        "REDIS_URL": (settings.redis_url, "redis", redis_port, "/0"),
        "CELERY_BROKER_URL": (settings.celery_broker_url, "redis", redis_port, "/0"),
        "CELERY_RESULT_BACKEND": (settings.celery_result_backend, "redis", redis_port, "/0"),
    }
    for name, (value, scheme, port, path) in destinations.items():
        try:
            parsed = urlparse(value)
            valid = (
                parsed.scheme == scheme
                and parsed.hostname == "127.0.0.1"
                and parsed.port == port
                and parsed.path == path
                and not parsed.params
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise AssertionError(f"{name} must use the isolated QA endpoint")
        explicitly_supplied = os.environ.get(name) == value
        if not explicitly_supplied:
            raise AssertionError(f"{name} must be explicitly supplied for this test")

    sync_matches = engine.url.render_as_string(hide_password=False) == settings.database_url
    async_matches = async_engine.url.render_as_string(
        hide_password=False
    ) == settings.database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if not sync_matches or not async_matches:
        raise AssertionError("database engine must match the isolated QA endpoint")
    celery_matches = all(
        (
            celery.conf.broker_url == settings.celery_broker_url,
            celery.conf.broker_read_url == settings.celery_broker_url,
            celery.conf.broker_write_url == settings.celery_broker_url,
            celery.conf.result_backend == settings.celery_result_backend,
        )
    )
    if not celery_matches:
        raise AssertionError("Celery destinations must match isolated QA endpoints")


@pytest.fixture
def isolated_service_db():
    _assert_isolated_service_targets()
    from app.database import Base, engine

    Base.metadata.create_all(engine)
