"""Live-service tests must reject unsafe destinations before connecting or publishing."""

import os
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

import pytest
import redis
import redis.asyncio as aioredis
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources.providers.dotenv import DotEnvSettingsSource
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

import app.database
from app.config import settings
from app.services.webhook_handler import process_github_webhook_task


@pytest.mark.parametrize(
    ("field", "unsafe_url"),
    [
        ("database_url", "postgresql+psycopg2://127.0.0.1:5433/webhook_db"),
        ("database_url", "postgresql+psycopg2://[::1]:55441/webhook_qa"),
        ("database_url", "postgresql+psycopg2://127.0.0.1.example:55441/webhook_qa"),
        ("redis_url", "redis://127.0.0.1:56381/1"),
        ("celery_broker_url", "redis://127.0.0.1:56382/0"),
        ("celery_result_backend", "redis://127.0.0.1:56381/1"),
    ],
    ids=["db-port", "db-ipv6", "db-host-suffix", "redis-db", "broker-port", "result-db"],
)
def test_unsafe_service_destination_blocks_before_io(field, unsafe_url, request, mocker):
    ddl = mocker.patch.object(app.database.Base.metadata, "create_all")
    db_connect = mocker.patch.object(app.database.engine, "connect")
    db_raw_connect = mocker.patch.object(app.database.engine, "raw_connection")
    async_connect = mocker.patch.object(AsyncEngine, "connect")
    redis_client = mocker.patch.object(redis.Redis, "from_url")
    async_redis_client = mocker.patch.object(aioredis, "from_url")
    publish = mocker.patch.object(process_github_webhook_task, "apply_async")
    mocker.patch.object(settings, field, unsafe_url)
    with pytest.raises(AssertionError, match="isolated QA endpoint"):
        request.getfixturevalue("isolated_service_db")
    for call in (
        ddl,
        db_connect,
        db_raw_connect,
        async_connect,
        redis_client,
        async_redis_client,
        publish,
    ):
        call.assert_not_called()


@pytest.mark.parametrize("field", ["CELERY_BROKER_READ_URL", "CELERY_BROKER_WRITE_URL"])
def test_celery_override_cannot_redirect_broker(field, request, mocker):
    ddl = mocker.patch.object(app.database.Base.metadata, "create_all")
    publish = mocker.patch.object(process_github_webhook_task, "apply_async")
    mocker.patch.dict(os.environ, {field: "redis://127.0.0.1:56382/0"})
    with pytest.raises(AssertionError):
        request.getfixturevalue("isolated_service_db")
    ddl.assert_not_called()
    publish.assert_not_called()


def test_env_file_alone_cannot_supply_live_service_target(request, mocker):
    ddl = mocker.patch.object(app.database.Base.metadata, "create_all")
    publish = mocker.patch.object(process_github_webhook_task, "apply_async")
    mocker.patch.dict(os.environ, {"CELERY_BROKER_URL": ""})
    with pytest.raises(AssertionError, match="explicitly supplied"):
        request.getfixturevalue("isolated_service_db")
    ddl.assert_not_called()
    publish.assert_not_called()


@pytest.mark.parametrize(
    ("name", "synthetic_value"),
    [
        ("PGHOSTADDR", "127.0.0.2"),
        ("PGSERVICE", "qa-test-service"),
        ("PGSERVICEFILE", "/tmp/qa-test-service.conf"),
        ("PGSYSCONFDIR", "/tmp/qa-test-system"),
    ],
)
def test_libpq_redirect_environment_blocks_before_io(name, synthetic_value, request, mocker):
    ddl = mocker.patch.object(app.database.Base.metadata, "create_all")
    db_connect = mocker.patch.object(app.database.engine, "connect")
    db_raw_connect = mocker.patch.object(app.database.engine, "raw_connection")
    driver_connect = mocker.patch("psycopg2.connect")
    publish = mocker.patch.object(process_github_webhook_task, "apply_async")
    mocker.patch.dict(os.environ, {name: synthetic_value})
    with pytest.raises(AssertionError, match=f"{name} must be unset"):
        request.getfixturevalue("isolated_service_db")
    for call in (ddl, db_connect, db_raw_connect, driver_connect, publish):
        call.assert_not_called()


@pytest.mark.parametrize("source", ["environment", "celery_override", "engine"])
def test_rejected_userinfo_is_absent_from_pytest_failure(source, request, mocker):
    marker = "SYNTHETIC_" + "USERINFO_NO_LEAK_20261007"
    if source == "environment":
        mocker.patch.dict(
            os.environ,
            {"CELERY_RESULT_BACKEND": f"redis://qa:{marker}@127.0.0.1:56381/0"},
        )
    elif source == "celery_override":
        mocker.patch.dict(
            os.environ,
            {"CELERY_BROKER_WRITE_URL": f"redis://qa:{marker}@127.0.0.1:56381/0"},
        )
    else:
        mocker.patch.object(
            app.database.engine,
            "url",
            make_url(f"postgresql+psycopg2://qa:{marker}@127.0.0.1:55441/webhook_qa"),
        )
    with pytest.raises(AssertionError) as failure:
        request.getfixturevalue("isolated_service_db")
    assert marker not in str(failure.getrepr(style="long"))


def test_failure_renderer_would_expose_an_unsafe_url_comparison():
    marker = "SYNTHETIC_" + "USERINFO_NO_LEAK_20261007"
    unsafe_url = f"redis://qa:{marker}@127.0.0.1:56381/0"
    with pytest.raises(AssertionError) as failure:
        assert unsafe_url == "redis://127.0.0.1:56381/0"
    assert marker in str(failure.getrepr(style="long"))


def test_test_settings_bootstrap_ignores_synthetic_dotenv(tmp_path, monkeypatch, mocker):
    sentinel = tmp_path / "synthetic.env"
    sentinel.write_text("QA_DOTENV_PROBE=from-synthetic-file\n")
    monkeypatch.delenv("QA_DOTENV_PROBE", raising=False)

    class ProbeSettings(BaseSettings):
        qa_dotenv_probe: str = "from-default"
        model_config = SettingsConfigDict(env_file=sentinel)

    read_file = mocker.patch.object(
        DotEnvSettingsSource,
        "_read_env_file",
        side_effect=AssertionError("test dotenv file read attempted"),
    )
    assert ProbeSettings().qa_dotenv_probe == "from-default"
    with pytest.raises(AssertionError, match="cannot load a dotenv file"):
        ProbeSettings(_env_file=sentinel)
    read_file.assert_not_called()


def test_pytest_startup_never_loads_a_dotenv_file(tmp_path):
    assert any(entry.name == "dotenv" for entry in entry_points(group="pytest11"))
    (tmp_path / ".env").write_text("QA_STARTUP_DOTENV_PROBE=from-synthetic-file\n")
    (tmp_path / "sitecustomize.py").write_text(
        "import os\n"
        "import dotenv\n"
        "os.environ['QA_STARTUP_INSTRUMENTED'] = 'yes'\n"
        "def reject_dotenv_read(*args, **kwargs):\n"
        "    raise RuntimeError('synthetic dotenv loader called during pytest startup')\n"
        "dotenv.find_dotenv = reject_dotenv_read\n"
        "dotenv.load_dotenv = reject_dotenv_read\n"
    )
    (tmp_path / "test_startup_probe.py").write_text(
        "import os\n"
        "def test_startup_without_dotenv(request):\n"
        "    assert os.environ.get('QA_STARTUP_INSTRUMENTED') == 'yes'\n"
        "    assert 'QA_STARTUP_DOTENV_PROBE' not in os.environ\n"
        "    assert not request.config.pluginmanager.hasplugin('dotenv')\n"
    )
    environment = os.environ.copy()
    for name in ("PYTEST_ADDOPTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTEST_PLUGINS"):
        environment.pop(name, None)
    environment.pop("QA_STARTUP_DOTENV_PROBE", None)
    environment["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(Path(__file__).resolve().parents[1] / "pytest.ini"),
            "test_startup_probe.py",
            "-q",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
