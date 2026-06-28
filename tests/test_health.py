"""health_check async DB 전환 (PR-3 / M2).

동기 SessionLocal 블로킹을 제거하고 get_async_db(AsyncSession)로 DB 연결을
확인한다. 아래 테스트는 async 세션이 await로 호출됨을 단언한다.
"""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import app.database
import app.main


def test_health_ok_uses_async_db():
    """정상: async 세션의 execute가 await되고 200/ok 반환."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=None)
    app.main.app.dependency_overrides[app.database.get_async_db] = lambda: db
    try:
        client = TestClient(app.main.app)
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
        db.execute.assert_awaited_once()  # 동기 블로킹이 아닌 async 경로
    finally:
        app.main.app.dependency_overrides.clear()


def test_health_unavailable_on_db_error():
    """DB 오류 시 503."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    app.main.app.dependency_overrides[app.database.get_async_db] = lambda: db
    try:
        client = TestClient(app.main.app, raise_server_exceptions=False)
        res = client.get("/health")
        assert res.status_code == 503
    finally:
        app.main.app.dependency_overrides.clear()
