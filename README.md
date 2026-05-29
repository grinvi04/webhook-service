# 프로덕션 수준 웹훅 서비스

[![CI](https://github.com/grinvi04/webhook-service/actions/workflows/ci.yml/badge.svg)](https://github.com/grinvi04/webhook-service/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.117-green.svg)
![License](https://img.shields.io/github/license/grinvi04/webhook-service)

FastAPI + Celery + PostgreSQL + Redis 기반의 멀티테넌트 웹훅 처리 서비스입니다.  
HMAC-SHA256 서명 검증, 비동기 큐 처리, 자동 재시도, Prometheus 모니터링을 갖춘 프로덕션 수준의 구현체입니다.

## 기능

- **멀티테넌트**: `tenant_id` 기반으로 여러 고객의 웹훅을 독립적으로 처리
- **다중 프로바이더**: GitHub(HMAC-SHA256), Stripe(Stripe SDK) 지원 — 플러그인 방식으로 확장 가능
- **서명 검증**: 각 프로바이더별 서명 검증으로 위변조 차단
- **비동기 처리**: Celery + Redis로 웹훅을 큐에 넣고 비동기 처리 (API 타임아웃 방지)
- **자동 재시도**: 실패한 태스크는 지수 백오프로 최대 3회 재시도, 이후 Dead Letter Queue
- **이벤트 재처리**: 관리자 API로 특정 이벤트를 큐에 다시 투입
- **데이터베이스 영속성**: 모든 수신 이벤트를 PostgreSQL에 기록 (감사·재처리용)
- **관리자 UI**: `/admin` — SQLAdmin 기반 웹 인터페이스
- **관찰 가능성**: 구조화 JSON 로깅, `/health`, `/metrics`(Prometheus), Grafana 대시보드

## 아키텍처

```
클라이언트 → Nginx(80) → FastAPI(8000) → Redis → Celery Worker → PostgreSQL
                                  ↓
                           Keycloak(8080)    Prometheus(9090) → Grafana(3000)
```

**기술 스택:**

| 역할 | 기술 |
|---|---|
| 웹 프레임워크 | FastAPI 0.117 |
| 비동기 작업 | Celery 5.5 + Redis 7 |
| 데이터베이스 | PostgreSQL 15 + SQLAlchemy 2.0 |
| DB 마이그레이션 | Alembic |
| 인증 | Keycloak 22 (JWT, Replay API) |
| 관리자 UI | SQLAdmin |
| 모니터링 | Prometheus + Grafana |
| 린팅 | ruff (line-length=88) |

## 지원 프로바이더

| 프로바이더 | 엔드포인트 | 서명 방식 | 큐 |
|---|---|---|---|
| GitHub | `POST /webhooks/{tenant_id}/github` | HMAC-SHA256 (`X-Hub-Signature-256`) | high_priority |
| Stripe | `POST /webhooks/{tenant_id}/stripe` | Stripe SDK (`Stripe-Signature`) | default |

새 프로바이더 추가는 `CLAUDE.md`의 체크리스트 또는 `/provider-add` 커맨드 참조.

## API 엔드포인트

| 메서드 | 경로 | 설명 | 인증 |
|---|---|---|---|
| GET | `/` | 서비스 실행 확인 | 없음 |
| GET | `/health` | DB 연결 포함 헬스 체크 | 없음 |
| GET | `/metrics` | Prometheus 메트릭 | 없음 |
| GET | `/docs` | Swagger UI | 없음 |
| POST | `/webhooks/{tenant_id}/{source}` | 웹훅 수신 (rate limit: 120/min) | HMAC 서명 |
| POST | `/webhooks/{tenant_id}/events/{event_id}/replay` | 이벤트 재처리 (rate limit: 5/min) | Keycloak JWT + admin 역할 |
| GET/POST | `/admin/*` | 관리자 웹 UI | Keycloak |

## 시작하기

### 전제 조건

- Docker 및 Docker Compose
- Python 3.11+ (로컬 개발 시)

### 1. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 값을 채웁니다.

**필수:**

| 변수 | 설명 | 예시 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 연결 URL | `postgresql+psycopg2://user:password@db:5432/webhook_db` |
| `CELERY_BROKER_URL` | Redis 브로커 URL | `redis://redis:6379/0` |
| `CELERY_RESULT_BACKEND` | Redis 결과 저장소 URL | `redis://redis:6379/0` |
| `GITHUB_WEBHOOK_SECRET` | GitHub 웹훅 HMAC 시크릿 | `my-super-secret-key` |
| `STRIPE_WEBHOOK_SECRET` | Stripe 웹훅 서명 시크릿 | `whsec_...` |

**선택 (PostgreSQL Docker용):**

| 변수 | 설명 |
|---|---|
| `POSTGRES_DB` | PostgreSQL 데이터베이스명 |
| `POSTGRES_USER` | PostgreSQL 사용자 |
| `POSTGRES_PASSWORD` | PostgreSQL 비밀번호 |

**선택 (관리자 계정):**

| 변수 | 설명 |
|---|---|
| `ADMIN_USERNAME` | 관리자 UI 사용자명 |
| `ADMIN_PASSWORD` | 관리자 UI 비밀번호 |

**선택 (Keycloak — Replay API 사용 시 필요):**

| 변수 | 기본값 | 설명 |
|---|---|---|
| `KEYCLOAK_URL` | `http://localhost:8080` | Keycloak 서버 URL |
| `KEYCLOAK_REALM` | `webhook-service` | Keycloak 렐름명 |
| `KEYCLOAK_CLIENT_ID` | `webhook-admin-client` | Keycloak 클라이언트 ID |
| `KEYCLOAK_CLIENT_SECRET` | (없음) | Keycloak 클라이언트 시크릿 |

### 2. Docker로 실행 (권장)

```bash
# 전체 스택 실행
docker-compose up --build -d

# DB 마이그레이션 적용
docker-compose exec web alembic upgrade head

# 로컬 테스트용 테넌트 생성
./scripts/seed_tenant.sh
```

서비스 접근:

| 서비스 | 주소 |
|---|---|
| API (nginx 경유) | `http://localhost` |
| API (직접) | `http://localhost:8000` |
| Swagger UI | `http://localhost:8000/docs` |
| 관리자 UI | `http://localhost:8000/admin` |
| Keycloak | `http://localhost:8080` |
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:3000` |

### 3. 로컬 개발 (Docker 없이)

```bash
# Python 3.11 가상환경 생성
python3.11 -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
pip install -r requirements-dev.txt

# DB + Redis만 Docker로 실행 (PostgreSQL 외부 포트: 5433)
docker-compose up -d db redis

# DB 마이그레이션
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  alembic upgrade head

# 터미널 1: Celery 워커
celery -A app.celery_worker.celery worker --loglevel=info

# 터미널 2: FastAPI 서버
uvicorn app.main:app --reload
```

> **macOS 15 주의:** Python 3.11과 libexpat 충돌이 발생할 수 있습니다.
> `brew install expat` 후 모든 명령어 앞에 아래를 붙여서 실행하세요:
> ```bash
> DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib uvicorn app.main:app --reload
> ```

## API 테스트

`docs/examples/` 디렉토리에 VS Code REST Client용 `.http` 예제 파일이 있습니다:

| 파일 | 내용 |
|---|---|
| `00_setup.http` | 헬스 체크, Swagger 링크 |
| `01_github_webhook.http` | GitHub 웹훅 성공/실패 케이스 |
| `02_stripe_webhook.http` | Stripe 웹훅 + Stripe CLI 안내 |
| `03_replay_event.http` | Replay API 인증·권한·404 케이스 |

`docs/examples/http.env`에서 `baseUrl`, `tenantId`, `webhookSecret` 등을 설정한 뒤 사용하세요.

**스크립트로 바로 테스트:**

```bash
# 테스트 테넌트 생성
./scripts/seed_tenant.sh

# GitHub 웹훅 전송 (서명 자동 생성)
./scripts/send_test_webhook.sh

# Stripe 웹훅은 Stripe CLI 사용
stripe listen --forward-to http://localhost:8000/webhooks/demo-tenant/stripe
stripe trigger customer.created
```

## Replay API 인증 (Keycloak)

Replay API는 Keycloak JWT 토큰 + `admin` 역할이 필요합니다.

```bash
# 토큰 발급
curl -X POST http://localhost:8080/realms/webhook-service/protocol/openid-connect/token \
  -d 'client_id=webhook-admin-client' \
  -d 'username=admin' \
  -d 'password=admin' \
  -d 'grant_type=password' \
  | jq -r '.access_token'

# 이벤트 재처리
curl -X POST http://localhost:8000/webhooks/demo-tenant/events/1/replay \
  -H "Authorization: Bearer <토큰>"
```

자세한 케이스는 `docs/examples/03_replay_event.http` 참조.

## 개발자 가이드

### 테스트 실행

```bash
# macOS (DYLD_LIBRARY_PATH 필요)
DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib \
  DATABASE_URL=postgresql+psycopg2://user:password@localhost:5433/webhook_db \
  pytest tests/ -v

# Linux / CI
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/webhook_db \
  pytest tests/ -v
```

### 린팅

```bash
ruff check app/ tests/
ruff format app/ tests/
```

### DB 마이그레이션

```bash
# 새 마이그레이션 생성
alembic revision --autogenerate -m "변경 내용 설명"

# 적용
alembic upgrade head

# 현재 상태 확인
alembic current
```

### 새 프로바이더 추가

Claude Code에서 `/provider-add <name> "<설명>"` 실행.  
수동으로 추가하려면 `CLAUDE.md`의 "새 프로바이더 추가 체크리스트" 참조.

## 디렉토리 구조

```
webhook-service/
├── alembic/               # DB 마이그레이션 스크립트
├── app/
│   ├── models/            # SQLAlchemy 모델
│   ├── schemas/           # Pydantic 스키마 (프로바이더별)
│   ├── services/          # 비즈니스 로직
│   ├── config.py          # 환경변수 설정
│   ├── celery_worker.py   # Celery 태스크 정의
│   ├── dependencies.py    # 서명 검증 의존성
│   ├── main.py            # FastAPI 앱, 엔드포인트
│   ├── metrics.py         # Prometheus 메트릭 정의
│   └── webhook_registry.py # 프로바이더 등록
├── docs/examples/         # VS Code REST Client 예제
├── scripts/               # 로컬 개발 유틸리티
├── tests/                 # 단위 + 통합 테스트
├── .claude/commands/      # Claude Code 슬래시 커맨드
├── .github/workflows/     # CI (GitHub Actions)
├── docker-compose.yml
├── Dockerfile
└── CLAUDE.md              # Claude Code 개발 가이드
```

## 모니터링

Prometheus 메트릭 (`/metrics`):

| 메트릭 | 타입 | 레이블 |
|---|---|---|
| `customer_webhook_total` | Counter | `customer_id`, `source` |
| `customer_webhook_errors_total` | Counter | `customer_id`, `source`, `error_type` |
| `webhook_processing_duration_seconds` | Histogram | `customer_id`, `source` |

Grafana 대시보드: `http://localhost:3000`
