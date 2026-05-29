# /api-test — API 테스트 (단위 + 통합 병렬)

**사용법**: `/api-test`

## 제약조건 (할루시네이션 방지)
- 테스트 작성 전 `tests/` 전체를 Read하여 기존 패턴 파악 필수
- FastAPI TestClient: `from fastapi.testclient import TestClient` 사용
- DB mock: `app.dependency_overrides[get_db] = lambda: mock_db` 패턴 (실제 DB 연결 금지)
- Prometheus 메트릭: `REGISTRY.get_sample_value(name, labels) or 0` → `.collect()` 패턴
- Celery 태스크: `task.apply_async` mock (`unittest.mock.patch` 사용)
- 테스트 간 메트릭 격리: 각 테스트에서 initial 값 먼저 측정 후 delta 비교

## 2개 에이전트 동시 background spawn

**Agent A — 단위 테스트** (`subagent_type: general-purpose`, `run_in_background: true`)
```bash
cd /Users/grinvi04/project/webhook-service
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/test_unit_tasks.py -v --tb=short
```
리포트: 통과/실패 수, 실패 테스트명·에러 첫 줄

**Agent B — 통합 테스트** (`subagent_type: general-purpose`, `run_in_background: true`)
```bash
cd /Users/grinvi04/project/webhook-service
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/test_integration_webhooks.py -v --tb=short
```
리포트: HTTP 상태코드별 시나리오 통과 여부, dependency_overrides 에러 여부

## 집계

| 테스트 | 통과 | 실패 | 소요시간 |
|---|---|---|---|
| 단위 | N | N | Xs |
| 통합 | N | N | Xs |

실패 시 에러 원문과 수정 방향 제시. 전체 통과 → "테스트 통과"

---

## 테스트 패턴 레퍼런스

### DB 의존성 오버라이드 (표준 패턴)
```python
from unittest.mock import MagicMock
from app.dependencies import get_db

mock_db = MagicMock()
app.dependency_overrides[get_db] = lambda: mock_db
yield
app.dependency_overrides.clear()
```

### Prometheus 메트릭 격리 패턴
```python
from prometheus_client import REGISTRY

# 테스트 전 초기값 스냅샷
before = REGISTRY.get_sample_value("customer_webhook_total",
    {"customer_id": "t1", "source": "github"}) or 0

# 동작 수행
response = client.post("/webhooks/t1/github", ...)

# delta 비교 (절대값 비교 금지 — 테스트 순서 의존성 생김)
after = REGISTRY.get_sample_value("customer_webhook_total",
    {"customer_id": "t1", "source": "github"}) or 0
assert after - before == 1
```

### Celery 태스크 mock 패턴
```python
from unittest.mock import patch

with patch("app.main.get_task") as mock_get_task:
    mock_task = MagicMock()
    mock_get_task.return_value = mock_task
    response = client.post(...)
    mock_task.apply_async.assert_called_once()
```

### pytest.mark.parametrize — 서명 검증 시나리오
```python
@pytest.mark.parametrize("header,body,expected_status", [
    (valid_sig, valid_body, 202),
    (None,      valid_body, 400),   # 헤더 없음
    ("bad_sig", valid_body, 401),   # 서명 불일치
])
def test_signature_scenarios(header, body, expected_status):
    ...
```

### 공통 pytest 픽스처 구조
```python
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()
```

### 테스트 커버리지 목표
| 파일 | 최소 커버리지 |
|---|---|
| app/dependencies.py | 90% |
| app/main.py | 85% |
| app/celery_worker.py | 80% |
