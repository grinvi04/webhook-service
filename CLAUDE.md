# Webhook Service — Claude Code 작업 규칙

## 행동 원칙

**코딩 전에 생각**: 가정을 명시. 불명확하면 멈추고 질문. 여러 해석이 가능하면 제시하고 선택받을 것.

**단순함 우선**: 요청한 것만 구현. 추측성 기능·추상화·유연성 금지. 50줄로 되면 200줄 쓰지 말 것.

**외과적 변경**: 건드려야 할 것만 건드림. 인접 코드·포맷 개선 금지. 내 변경이 만든 orphan(미사용 import 등)만 정리.

**목표 기반 실행**: 작업을 검증 가능한 목표로 변환. "버그 수정" → "재현 테스트 작성 후 통과시키기".

---

## 커맨드 강제 사용 규칙

> **모든 작업 시작 전**: 어떤 슬래시 커맨드를 사용할지 먼저 선언하고 사용자 확인을 받을 것. 파일 종류·작업 크기와 무관하게 예외 없음.

**파일 수정·생성·삭제 및 git 작업 전에 반드시 아래 커맨드를 먼저 실행한다.**

| 상황 | 커맨드 |
|---|---|
| 운영 중 긴급 버그 (main 기준) | `/hotfix <name> "<증상>"` |
| 배포 중 버그·긴급 수정 (develop 기준) | `/feature-modify <name> "<설명>"` → fix/* 브랜치 사용 |
| 신규 기능 개발 (develop 기준) | `/feature-add <name> "<설명>"` |
| 기존 기능 변경 (develop 기준) | `/feature-modify <name> "<설명>"` |
| feature 브랜치 → develop 머지 | `/feature-merge` |
| 새 웹훅 프로바이더 추가 | `/provider-add <name> "<설명>"` |
| DB 스키마 변경 | `/migration-add <설명>` |
| 릴리즈 전 검증 | `/release-check` |
| 릴리즈 실행 | `/release <version>` |
| `.claude/`·인프라 파일 변경 | `/feature-modify <name> "<설명>"` |
| 작업 계획 수립 | `/work-plan "<설명>"` |

**예외 (파일 편집에만 해당 — git 작업은 예외 없이 커맨드 필수)**:
- `.claude/`, `CLAUDE.md`, `README.md`, `requirements.txt`, `docker-compose*.yml` 등은 슬래시 커맨드 없이 **파일 편집만** 허용
- 단, 브랜치 생성·커밋·머지는 반드시 위 커맨드를 통할 것. 직접 git 명령 금지.

**커밋은 파일 종류와 무관하게 항상 feature/fix/hotfix/release 브랜치에서 할 것.**

**커맨드가 없거나 불명확하면 멈추고 사용자에게 먼저 물어볼 것. 임의로 판단하지 말 것.**

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

### ⛔ 커맨드 우회 금지

**Claude는 커맨드 파일을 직접 읽고 Bash로 임의 재구성하지 않는다.**

- 커맨드는 사용자가 `/command-name` 으로 호출한다 — Claude가 자의로 실행하지 않는다
- 커맨드의 Phase 순서, 서브에이전트 spawn, 검증 게이트를 편의를 위해 생략하지 않는다
- 해당 커맨드가 존재하는데 Bash로 직접 처리하는 것은 하네스 위반이다

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
