# Webhook Service — Claude Code 작업 규칙

## 프로젝트 개요

FastAPI + Celery + PostgreSQL + Redis 기반의 멀티테넌트 웹훅 수신·처리 서비스.

| 레이어 | 기술 |
|---|---|
| API | FastAPI 0.117, Python 3.11 |
| 비동기 작업 | Celery 5.5 + Redis 7 |
| DB | PostgreSQL 15 + SQLAlchemy 2.0 (동기) + Alembic |
| 인증 | Keycloak (JWT Bearer) |
| 메트릭 | Prometheus (prometheus-client + prometheus-fastapi-instrumentator) |
| Admin UI | sqladmin + itsdangerous |
| 린터 | ruff (E, F, W, I, UP 규칙, line-length=88) |

---

## 로컬 개발 환경 설정

### 사전 조건

- Python 3.11
- Docker Desktop (PostgreSQL + Redis 컨테이너)
- DriveTree 프로젝트도 함께 실행 중이면 **포트 충돌 주의** (아래 참조)

### macOS — Python 3.11 libexpat 이슈

macOS 15(Sequoia)에서 Homebrew Python 3.11은 시스템 `libexpat`과 버전 불일치 문제가 있다.  
venv 생성·pip 설치·pytest 실행 시 반드시 `DYLD_LIBRARY_PATH`를 앞에 붙여야 한다.

```bash
# Homebrew expat 설치 (최초 1회)
brew install expat
```

이후 모든 명령에 `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib`를 prefix로 사용한다 (아래 세팅 참조).

### 최초 세팅

```bash
# 1. 가상환경 생성 및 의존성 설치
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib python3.11 -m venv .venv
source .venv/bin/activate
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib pip install -r requirements.txt -r requirements-dev.txt

# 2. 환경변수 파일 준비
cp .env.example .env
# .env 수정 — DATABASE_URL, secrets 등

# 3. 컨테이너 실행 (DB + Redis만)
docker-compose up -d db redis

# 4. DB 마이그레이션
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  alembic upgrade head

# 5. 개발 서버 실행
uvicorn app.main:app --reload
```

### 포트 충돌 주의 (DriveTree 병행 실행 시)

DriveTree도 PostgreSQL 5432 포트를 사용한다.  
webhook-service `docker-compose.yml`의 db 서비스는 **호스트 5433 → 컨테이너 5432**로 매핑되어 있다.

```
# .env 로컬 개발용 DATABASE_URL
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db
```

Docker Compose 내부 서비스 간 통신(web, worker)은 여전히 `db:5432`를 사용하므로 `.env`의 `DATABASE_URL`은 `@db:5432`로 유지한다.

---

## 테스트 실행

```bash
# macOS: DYLD_LIBRARY_PATH 필수
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  pytest tests/ -v

# 특정 테스트만
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  pytest tests/test_integration_webhooks.py -v -k "test_receive_github"
```

### 테스트 환경 특이사항

- `pytest.ini`에 `env_files = .env`가 설정되어 있지만, **로컬 `.env`의 `DATABASE_URL`은 도커 내부 주소(`@db:5432`)**이므로 CLI에서 환경변수를 덮어써야 한다.
- `pytest.ini`의 `--doctest-modules` 옵션 때문에 `norecursedirs = alembic` 설정이 필수다 (alembic 마이그레이션 파일에 doctest가 없어도 import 시도함).

---

## 아키텍처 핵심 규칙

### 파일 구조

```
app/
  config.py          ← pydantic-settings (Settings 싱글턴)
  database.py        ← SQLAlchemy engine, SessionLocal, Base, get_db()
  metrics.py         ← Prometheus 메트릭 정의 (Counter, Histogram)
  dependencies.py    ← FastAPI Depends 함수들: get_db, get_current_user, WebhookVerifier, limiter
  webhook_registry.py ← TASK_REGISTRY: source → Celery Task 매핑
  main.py            ← FastAPI app 인스턴스, 라우터, 미들웨어
  admin.py           ← sqladmin Admin UI 설정
  celery_worker.py   ← Celery 인스턴스
  models/            ← SQLAlchemy ORM 모델
  schemas/           ← Pydantic 요청/응답 스키마
  services/          ← Celery 태스크 (webhook_handler.py)
tests/
  test_integration_webhooks.py  ← FastAPI TestClient 통합 테스트
  test_unit_tasks.py            ← Celery 태스크 유닛 테스트
```

### 순환 임포트 방지 규칙

이 프로젝트는 `main.py`가 `admin.py`, `dependencies.py`, `services/webhook_handler.py` 등을 임포트하는 구조라 **순환 임포트가 발생하기 쉽다**.

**반드시 지킬 규칙:**

1. **Prometheus 메트릭은 `app/metrics.py`에만 정의한다.**  
   `main.py`나 다른 모듈에서 정의하면 `webhook_handler.py`가 임포트할 때 순환이 발생한다.

2. **`admin.py`에서 `main.py`를 절대 임포트하지 않는다.**  
   Keycloak 등 `main.py`에서 생성된 객체가 필요하면 `request.app.state`를 통해 접근한다:
   ```python
   # ❌ 금지
   from app.main import keycloak_openid

   # ✅ 올바른 방법
   keycloak_openid = request.app.state.keycloak_openid
   ```

3. **`services/webhook_handler.py`에서 `main.py`를 임포트하지 않는다.**  
   메트릭, 설정 등은 각자의 모듈(`metrics.py`, `config.py`)에서 임포트한다.

### app.state 사용 패턴

`main.py`에서 앱 시작 시 공유 객체를 `app.state`에 등록한다:

```python
app.state.keycloak_openid = keycloak_openid
```

`dependencies.py`의 `get_current_user` 등 request를 받는 함수에서는 `request.app.state.keycloak_openid`로 접근한다.

---

## FastAPI 의존성 주입 테스트 규칙

FastAPI의 `Depends()`는 함수 참조를 데코레이터 시점에 저장한다.  
**`mocker.patch("app.dependencies.get_current_user")`는 효과가 없다** — FastAPI가 이미 원본 함수 참조를 갖고 있기 때문.

```python
# ❌ 동작하지 않음
mocker.patch("app.dependencies.get_current_user", return_value=mock_user)

# ✅ 올바른 방법 — dependency_overrides 사용
from app.dependencies import get_current_user
app.main.app.dependency_overrides[get_current_user] = lambda: mock_user_info

# 테스트 후 반드시 정리
app.main.app.dependency_overrides.clear()
```

---

## Prometheus 메트릭 테스트 규칙

`REGISTRY.get_sample_value()`는 counter 이름 규칙(`_total` suffix) 때문에 `None`을 반환하는 경우가 있다.  
**Counter를 테스트할 때는 `.collect()`를 직접 사용한다:**

```python
def _counter_value(counter, **labels):
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == labels:
                return sample.value
    return 0.0

# 사용 예
initial = _counter_value(CUSTOMER_WEBHOOK_TOTAL, customer_id="id", source="github")
# ... 요청 실행 ...
assert _counter_value(CUSTOMER_WEBHOOK_TOTAL, customer_id="id", source="github") == initial + 1
```

---

## Celery 태스크 에러 메트릭 규칙

Celery의 `on_failure` 훅은 **실제 워커 프로세스**에서만 호출된다.  
테스트에서 `.run()` 또는 `CELERY_TASK_ALWAYS_EAGER`로 직접 실행하면 `on_failure`가 **호출되지 않는다**.

따라서 에러 메트릭 증가는 `on_failure`에만 의존하지 말고 **`except` 블록 안에서도 처리**한다:

```python
except Exception as e:
    CUSTOMER_WEBHOOK_ERRORS_TOTAL.labels(
        customer_id=str(customer_id),
        source="github",
        error_type=type(e).__name__,
    ).inc()
    raise
```

---

## Ruff 린트 규칙

`pyproject.toml` 기준 활성화 규칙: `E, F, W, I, UP` (line-length=88)

자주 발생하는 위반:

| 규칙 | 내용 | 수정 방법 |
|---|---|---|
| UP007 | `Optional[X]` → `X \| None`, `Union[X, Y]` → `X \| Y` | 직접 치환 |
| UP035 | `from typing import Callable` → `from collections.abc import Callable` | import 경로 변경 |
| F401 | 미사용 import | 삭제 |
| I001 | import 순서 (stdlib → third-party → local) | isort 규칙 적용 |
| E501 | 라인 길이 88자 초과 | 줄 분리 또는 주석 제거 |

```bash
# 린트 검사
ruff check .

# 자동 수정 가능한 항목 수정
ruff check . --fix

# 포맷 검사
ruff format --check .

# 포맷 적용
ruff format .
```

---

## Alembic 마이그레이션 워크플로우

```bash
# 1. models/ 에서 SQLAlchemy 모델 수정

# 2. 마이그레이션 파일 자동 생성
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  alembic revision --autogenerate -m "설명적인_마이그레이션명"

# 3. 생성된 파일 검토 (alembic/versions/ 디렉토리)
# UP007 위반(Optional[X]) 등 ruff 위반 여부 확인 후 수정

# 4. 마이그레이션 적용
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  alembic upgrade head

# 5. 롤백 (필요 시)
alembic downgrade -1
```

> **주의**: `alembic/versions/` 파일은 자동 생성되므로 ruff UP007(`Optional[X]`) 위반이 자주 발생한다. 생성 직후 수동으로 수정하거나 `ruff check --fix`로 자동 수정한다.

---

## SQLAlchemy 관계 정의 규칙

`back_populates`를 사용하면 **양쪽 모델 모두**에 관계를 정의해야 한다.

```python
# app/models/customer.py
class Customer(Base):
    events = relationship("WebhookEvent", back_populates="customer")

# app/models/webhook_event.py — 반드시 대응하는 관계 추가
class WebhookEvent(Base):
    customer = relationship("Customer", back_populates="events")
```

한쪽만 정의하면 SQLAlchemy가 `KeyError`를 발생시키며 앱이 시작되지 않는다.

---

## 새 Webhook Provider 추가 패턴

1. **`app/schemas/`** — Pydantic 요청 스키마 추가 (`{provider}_webhook.py`)
2. **`app/services/webhook_handler.py`** — Celery 태스크 추가 (`process_{provider}_webhook_task`)
3. **`app/dependencies.py`** — `WebhookVerifier._verify_{provider}()` 메서드 추가
4. **`app/webhooks.py`** — 라우터에 엔드포인트 추가 (`POST /webhooks/{tenant_id}/{provider}`)
5. **`app/main.py`** — `register_webhook("{provider}", process_{provider}_webhook_task)` 등록
6. **`tests/test_integration_webhooks.py`** — 성공/실패/비활성 테넌트 테스트 추가
7. **`tests/test_unit_tasks.py`** — 태스크 유닛 테스트 추가

---

## CI/CD

### GitHub Actions (`.github/workflows/ci.yml`)

- Python 3.11 사용
- `services:` 블록으로 PostgreSQL 15, Redis 7 컨테이너 제공
- `DATABASE_URL`: CI 환경에서는 `postgresql+psycopg2://postgres:postgres@localhost:5432/test_db` (고정값, Secret 불필요)
- ruff lint/format → pytest → Docker 이미지 빌드·push (GHCR) 순서로 실행

### CI 환경변수

| 변수 | CI 값 | 비고 |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/test_db` | services 블록과 일치 |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | services 블록과 일치 |
| `GITHUB_WEBHOOK_SECRET` | GitHub Secret | 실제 값 필요 |
| `STRIPE_WEBHOOK_SECRET` | GitHub Secret | 실제 값 필요 |

---

## API 수동 테스트 (docs/examples/)

VS Code REST Client 확장 설치 후 `docs/examples/` 파일을 열면 바로 실행 가능하다.

| 파일 | 설명 |
|---|---|
| `00_setup.http` | 헬스 체크, Swagger UI 링크 |
| `01_github_webhook.http` | GitHub HMAC-SHA256 서명 검증 성공/실패 케이스 |
| `02_stripe_webhook.http` | Stripe 서명 검증 성공/실패 케이스 |
| `03_replay_event.http` | Replay API 인증·권한 케이스 |
| `http.env` | 환경변수 (`baseUrl`, `tenantId`, `webhookSecret` 등) |

### 테스트 테넌트 생성

```bash
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  ./scripts/seed_tenant.sh
```

### GitHub 서명 생성

```bash
PAYLOAD='{"action":"opened","sender":{"login":"octocat"},"repository":{"full_name":"octocat/hello-world"}}'
./scripts/generate_github_signature.sh "$PAYLOAD" "my-super-secret-key"
# → sha256=abc123...   (01_github_webhook.http의 githubSignature에 붙여넣기)
```

### 웹훅 전송 한방 스크립트

```bash
# 서버 실행 후
./scripts/send_test_webhook.sh          # GitHub 웹훅
./scripts/send_test_webhook.sh stripe   # Stripe (Stripe CLI 안내)
```

---

## 커밋 전 체크리스트

```bash
# 린트 + 포맷 검사
ruff check .
ruff format --check .

# 테스트 전체 통과 확인 (macOS: DYLD_LIBRARY_PATH 필수)
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  pytest tests/ -v
```

모든 테스트가 통과한 상태에서만 커밋한다. failing 테스트가 있으면 커밋하지 않는다.

---

## Keycloak 설정

로컬 개발에서 Keycloak 전체 스택은 `docker-compose up` 시 자동으로 실행된다.

| 항목 | 값 |
|---|---|
| Admin 콘솔 | `http://localhost:8080` |
| Admin 계정 | admin / admin |
| Realm | `webhook-service` |
| Client ID | `webhook-admin-client` |

테스트 환경에서는 `get_current_user` 의존성을 `dependency_overrides`로 우회한다 (실제 Keycloak 서버 불필요).
