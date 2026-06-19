# Webhook Service — Claude Code 작업 규칙


## Claude Code 전용 지침

- git-flow 작업은 harness-guard 플러그인 커맨드 사용: `/feature-merge`, `/hotfix`, `/release-check`, `/release` (그 외 `/feature-add`, `/feature-modify`, `/provider-add`, `/migration-add`, `/work-plan`, `/api-test`, `/readme-update` 제공)
- PR 머지 전 게이트는 `pr-review-gate` 스킬 절차를 따른다 (단일 출처)
- 릴리즈 전 보안 검토는 `security-reviewer` 에이전트를 spawn한다
- `main`·`develop` 직접 커밋 금지, PR·승인·CI 통과 강제는 GitHub branch protection이 담당한다 (아래 Git Flow 참조)
- `.claude/`는 `.gitignore`로 Git 추적 제외 — 커맨드/훅 변경은 harness 원본 수정 후 동기화

---

## 프로젝트 개요

FastAPI + Celery + PostgreSQL + Redis 기반 멀티테넌트 웹훅 처리 서비스.

| 레이어 | 기술 |
|---|---|
| API | FastAPI 0.117, Python 3.11, Pydantic v2 |
| 비동기 작업 | Celery 5.5 + Redis 7 (high_priority / default / dead_letters 큐) |
| DB | PostgreSQL 15 + SQLAlchemy 2.0 (동기) + Alembic |
| 인증 | Keycloak 22 (JWT Bearer, Replay API) |
| 메트릭 | Prometheus (prometheus-client + prometheus-fastapi-instrumentator) |
| 린터 | ruff (E, F, W, I, UP, line-length=88) |

슬래시 커맨드: `/work-plan`, `/feature-add`, `/feature-modify`, `/feature-merge`, `/hotfix`, `/provider-add`, `/migration-add`, `/api-test`, `/release-check`, `/release`, `/readme-update`

---

## 로컬 개발 필수 사항

### macOS 15 libexpat 이슈 (HARD REQUIREMENT)

모든 Python 명령어 앞에 반드시 prefix 적용:
```bash
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib <명령어>
```

```bash
# 테스트
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -v

# lint
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
```

### 포트 주의

로컬 개발 DB: 호스트 **5433** → 컨테이너 5432 (DriveTree가 5432 점유).
Docker 내부 서비스 간 통신은 `db:5432` 그대로 사용.

---

## 아키텍처 핵심 규칙

### async/sync 혼용 금지

`async def` 엔드포인트에서 동기 SQLAlchemy 세션(`db.query`, `db.commit`) 직접 호출 **금지** — 이벤트 루프 블로킹.

```python
# ❌ async 엔드포인트에서 동기 DB 호출
async def receive_webhook(..., db: Session = Depends(get_db)):
    db.query(WebhookEvent).filter(...)  # 이벤트 루프를 블로킹

# ✅ 선택지 A — 동기 유지: def로 변경 (FastAPI가 스레드풀 위임)
def receive_webhook(..., db: Session = Depends(get_db)):
    ...

# ✅ 선택지 B — async 전환: create_async_engine + AsyncSession
async def receive_webhook(..., db: AsyncSession = Depends(get_async_db)):
    await db.execute(...)
```

`get_db`가 `database.py`와 `dependencies.py`에 중복 정의되어 있음. **`database.get_db`만 사용** (중복 제거 필요).

### SessionMiddleware 등록 확인

`admin.py`는 `request.session`을 읽고 씁니다. **`app/main.py`에 반드시 등록** 되어야 함:

```python
from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET)
```

SessionMiddleware 없이 `request.session` 접근 시 런타임 에러.

### 순환 임포트 방지

`main.py → admin.py → main.py` 순환이 발생하기 쉬운 구조.

1. **Prometheus 메트릭은 `app/metrics.py`에만 정의** — `main.py`나 `webhook_handler.py`에 정의하면 순환 발생
2. **`admin.py`에서 `main.py` import 금지** — Keycloak 등 공유 객체는 `request.app.state`로 접근:
   ```python
   # ❌ from app.main import keycloak_openid
   # ✅ keycloak_openid = request.app.state.keycloak_openid
   ```
3. **`services/webhook_handler.py`에서 `main.py` import 금지** — 메트릭은 `metrics.py`, 설정은 `config.py`에서

### 파일 역할

```
app/metrics.py          ← Prometheus Counter·Histogram 정의 (유일한 위치)
app/dependencies.py     ← get_db, get_current_user, WebhookVerifier, limiter
app/webhook_registry.py ← WEBHOOK_REGISTRY: source → Celery Task 매핑
app/services/webhook_handler.py ← Celery 태스크 구현
```

---

## Celery 규칙

### 재시도 패턴 — autoretry_for 필수

`max_retries`만 설정하면 재시도가 실행되지 않음. `autoretry_for` + `retry_backoff` 또는 `self.retry()` 필수:

```python
@app.task(
    bind=True,
    max_retries=3,
    autoretry_for=(SQLAlchemyError, redis.exceptions.RedisError),
    retry_backoff=True,
    acks_late=True,
)
def process_webhook(self, payload, customer_id):
    ...
# 또는 except 블록에서: raise self.retry(exc=e, countdown=60)
```

### DLQ 연결 확인

`send_to_dlq` 태스크는 정의만이 아니라 `on_failure` 핸들러에서 실제로 호출해야 함:

```python
def on_failure(self, exc, task_id, args, kwargs, einfo):
    send_to_dlq.apply_async(args=[...], queue="dead_letters")
```

---

## 테스트 규칙

### FastAPI 의존성 mock — dependency_overrides 필수

`mocker.patch("app.dependencies.get_current_user")` **동작하지 않음** — FastAPI가 데코레이터 시점에 원본 참조를 고정하기 때문.

```python
# ✅ 올바른 방법
from app.dependencies import get_current_user, get_db
app.dependency_overrides[get_db] = lambda: mock_db
app.dependency_overrides[get_current_user] = lambda: mock_user
# 테스트 후 반드시
app.dependency_overrides.clear()
```

### Prometheus 메트릭 테스트 — collect() 패턴 필수

`REGISTRY.get_sample_value()`는 `_total` suffix 규칙 때문에 `None` 반환 가능. `.collect()` 직접 사용:

```python
def _counter_value(counter, **labels):
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == labels:
                return sample.value
    return 0.0

# delta 비교 — 절대값 비교 금지 (테스트 순서 의존성 생김)
before = _counter_value(CUSTOMER_WEBHOOK_TOTAL, customer_id="t1", source="github")
# ... 요청 실행 ...
assert _counter_value(CUSTOMER_WEBHOOK_TOTAL, customer_id="t1", source="github") == before + 1
```

### Celery on_failure 주의

`on_failure` 훅은 **실제 워커 프로세스**에서만 호출됨. `.run()` 또는 `ALWAYS_EAGER`로 테스트 시 호출되지 않음.
에러 메트릭 증가는 `except` 블록 안에서도 처리할 것.

---

## 보안 규칙

- HMAC 비교: 반드시 `hmac.compare_digest()` 사용 (`==` 금지 — 타이밍 공격)
- 새 provider 서명 검증 시 헤더 없음 → 400, 불일치 → 401 구분
- Replay API: Keycloak JWT + `admin` 역할 필수, `event_id` + `customer_id` 동시 필터링

---

## Git Flow

| 브랜치 | 직접 커밋 |
|---|---|
| `main`, `develop` | ❌ **절대 금지 — 배포 크래시, 긴급 버그 등 어떤 상황도 예외 없음** |
| `feature/*`, `fix/*`, `hotfix/*`, `release/*` | ✅ |

**기능 개발**: `develop → feature/xxx → PR → develop`
**긴급 수정**: `develop → fix/xxx → PR → develop` (배포 중 버그, 마이그레이션 누락 등 포함)
**운영 핫픽스**: `main → hotfix/xxx → PR → main (tag) + develop`
**릴리즈**: `develop → release/vX.X.X → PR → main (tag) + develop`

> ⛔ "빠르게 해야 한다", "작은 수정이다", "긴급하다" — 모두 브랜치를 건너뛸 이유가 되지 않는다.

---

## 커밋 전 체크리스트

pre-commit이 자동 실행하지만 수동 확인:
```bash
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib .venv/bin/ruff check app/ tests/
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  .venv/bin/pytest tests/ -q
```

커밋 메시지 형식: `타입(범위): 제목` + `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

---

## Compact Instructions

컨텍스트 압축 후에도 반드시 유지해야 할 핵심 규칙:

1. **Git Flow**: `main`, `develop` 직접 커밋 금지 (branch protection으로 강제). feature/fix/hotfix/release 브랜치 → PR 경유.
2. **macOS 15 필수 prefix**: 모든 Python 명령 앞에 `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib` 추가.
3. **로컬 DB 포트**: 호스트 **5433** (Docker 내부 서비스 간은 `db:5432` 그대로).
4. **순환 임포트 방지**: Prometheus 메트릭은 `app/metrics.py`에만 정의. `admin.py`에서 `main.py` import 금지.
5. **HMAC 비교**: 반드시 `hmac.compare_digest()` 사용 (`==` 금지 — 타이밍 공격).
6. **테스트 규칙**: FastAPI 의존성 모킹 시 `dependency_overrides` 사용 필수. Prometheus 메트릭 검증 시 `collect()` 패턴 사용 필수.
7. **async/sync 혼용 금지**: `async def` 엔드포인트에서 동기 `db.query`/`db.commit` 직접 호출 금지 — 이벤트 루프 블로킹.
8. **Celery retry 필수**: `max_retries`만으론 재시도 0회 — `autoretry_for=(SQLAlchemyError, ...)` 또는 `self.retry(exc=e)` 필수.
9. **SessionMiddleware 등록 필수**: `admin.py`가 `request.session` 사용 — `app/main.py`에 `SessionMiddleware` 등록 없으면 런타임 에러.
