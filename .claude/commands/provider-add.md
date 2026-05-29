# /provider-add — 새 웹훅 프로바이더 추가

**사용법**: `/provider-add <provider> "<설명>"`  예) `/provider-add slack "Slack 이벤트 처리"`

## 제약조건 (할루시네이션 방지)
- 코드 작성 전 반드시 아래 파일을 Read하여 실제 패턴을 확인할 것
  - `app/dependencies.py` — 서명 검증 함수 구조 (verify_github_signature 참고)
  - `app/celery_worker.py` — Celery 태스크 구조 (@app.task 데코레이터 패턴)
  - `app/webhook_registry.py` — WEBHOOK_REGISTRY 딕셔너리 구조
  - `app/webhooks.py` — 엔드포인트 등록 패턴
- 존재하지 않는 모듈/클래스/함수 import 금지 — requirements.txt 확인 후 사용
- Pydantic v2: `class Config` 사용 금지 → `model_config = ConfigDict(...)` 사용
- HMAC 비교는 반드시 `hmac.compare_digest()` 사용 (`==` 금지 — 타이밍 공격 취약)
- ruff: 라인 길이 88자 이하, UP007(str | None), F401(미사용 import) 준수

## 실행 절차

### 1. 사전 확인 (직접 실행)
위 4개 파일 Read 후 기존 패턴 파악.

### 2. 병렬 에이전트 (동시에 background spawn)

**Agent A — 애플리케이션 코드** (`subagent_type: general-purpose`, `run_in_background: true`)
- `app/schemas/<provider>_webhook.py`: Pydantic v2 BaseModel 페이로드 스키마
- `app/dependencies.py`: `verify_<provider>_signature(request, db, tenant_id)` 추가
  - 서명 헤더 없음 → `HTTPException(400)`
  - 서명 불일치 → `HTTPException(401)`
  - `hmac.compare_digest()` 필수
- `app/celery_worker.py`: `process_<provider>_webhook_task` 추가
  - `@app.task(name="tasks.process_<provider>_webhook_task", bind=True, max_retries=3)`
  - `self.retry(exc=exc, countdown=60)` 패턴
- `app/webhook_registry.py`: WEBHOOK_REGISTRY에 등록
- `app/webhooks.py`: `POST /webhooks/{tenant_id}/<provider>` 엔드포인트 추가
  - Prometheus 메트릭 카운터 포함 (app/metrics.py 참고)

**Agent B — 테스트** (`subagent_type: general-purpose`, `run_in_background: true`)
- 기존 `tests/test_unit_tasks.py`, `tests/test_integration_webhooks.py` Read 후 동일 패턴 적용
- `dependency_overrides`로 DB mock (실제 DB 연결 금지)
- Prometheus: `REGISTRY.get_sample_value(metric, labels) or 0` → `.collect()` 패턴
- 커버리지: 서명 성공(202) / 헤더 없음(400) / 잘못된 서명(401) / 없는 테넌트(404)

### 3. 검증
```bash
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -v -k "<provider>"
```

### 4. 커밋
`feat: <provider> 웹훅 프로바이더 추가`

---

## 패턴 레퍼런스

### Stripe SDK 서명 검증 패턴
```python
import stripe
from stripe import SignatureVerificationError

header = request.headers.get("Stripe-Signature")
try:
    event = stripe.Webhook.construct_event(body, header, secret)
except SignatureVerificationError:
    raise HTTPException(status_code=401, detail="Invalid Stripe signature")
```

### 순수 HMAC-SHA256 패턴 (GitHub 등)
```python
import hashlib, hmac

expected = "sha256=" + hmac.new(
    secret.encode(), body, hashlib.sha256
).hexdigest()
if not hmac.compare_digest(expected, received):
    raise HTTPException(status_code=401, detail="Invalid signature")
```

### Celery 지수 백오프 재시도
```python
raise self.retry(exc=exc, countdown=2 ** self.request.retries * 60)
# retries=0 → 60s, retries=1 → 120s, retries=2 → 240s
```

### 큐 라우팅 결정 기준 (app/main.py)
- `high_priority`: GitHub, 실시간성 높은 이벤트
- `default`: Stripe, 배치성 이벤트
- 새 프로바이더 추가 시 SLA 기준으로 큐 결정 후 주석 작성
