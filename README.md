# 프로덕션 수준 웹훅 서비스

[![CI](https://github.com/grinvi04/webhook-service/actions/workflows/ci.yml/badge.svg)](https://github.com/grinvi04/webhook-service/actions/workflows/ci.yml)

이 프로젝트는 Python, FastAPI, Celery, SQLAlchemy로 구축된 견고하고 확장 가능하며 프로덕션 수준의 웹훅 처리 서비스입니다.

## 기능

- **다중 공급자 지원**: 모든 공급자(예: GitHub, Stripe)의 웹훅을 쉽게 확장하여 지원합니다.
- **보안**: 서명 확인(HMAC-SHA256)을 사용하여 수신 웹훅의 유효성을 검사합니다.
- **안정적인 백그라운드 처리**: Celery 및 Redis를 사용하여 웹훅을 비동기적으로 큐에 넣고 처리하여 데이터 손실 및 API 시간 초과를 방지합니다.
- **자동 재시도**: 실패한 웹훅 처리 작업은 지수 백오프를 사용하여 자동으로 재시도됩니다.
- **데이터베이스 영속성**: 모든 수신 이벤트는 감사 및 재생을 위해 데이터베이스(SQLite/PostgreSQL)에 기록됩니다.
- **데이터베이스 마이그레이션**: Alembic을 사용하여 데이터베이스 스키마 변경을 안전하게 관리합니다.
- **관리자 UI**: 수신된 웹훅 이벤트를 보고, 검색하고, 관리하기 위한 `/admin`의 웹 인터페이스입니다.
- **이벤트 재생**: 데이터베이스에서 모든 이벤트를 다시 큐에 넣고 다시 처리하기 위한 API 엔드포인트입니다.
- **관찰 가능성**:
    - 쉬운 분석을 위한 구조화된 JSON 로깅.
    - 서비스 상태 확인을 위한 `/health` 엔드포인트.
    - Prometheus 모니터링을 위한 `/metrics` 엔드포인트.
- **자동화된 DX**: 린팅/포맷팅을 위한 `ruff`, 품질 관리를 위한 `pre-commit` 훅, GitHub Actions를 통한 CI 파이프라인이 함께 제공됩니다.

## 아키텍처

- **웹 프레임워크**: FastAPI
- **백그라운드 작업**: Celery
- **메시지 브로커**: Redis
- **데이터베이스**: SQLAlchemy (SQLite 및 PostgreSQL 지원)
- **DB 마이그레이션**: Alembic
- **관리자 UI**: SQLAdmin

### 디렉토리 구조
```
/webhook-service/
├── alembic/               # 데이터베이스 마이그레이션 스크립트
├── app/                   # 메인 애플리케이션 코드
│   ├── services/          # 비즈니스 로직 (Celery 작업)
│   ├── models/            # SQLAlchemy DB 모델
│   ├── schemas/           # Pydantic 스키마
│   ├── dependencies.py    # FastAPI 종속성 (예: 검증기)
│   ├── webhook_registry.py # 새 웹훅 소스 등록 로직
│   ├── main.py            # FastAPI 앱, 엔드포인트
│   └── ...
├── tests/                 # 통합 및 단위 테스트
├── .github/workflows/     # CI 파이프라인 (GitHub Actions)
├── .env.example           # 환경 변수 템플릿
├── docker-compose.yml     # Docker 서비스 정의
├── Dockerfile             # Docker 이미지 정의
├── pyproject.toml         # 프로젝트 구성 (ruff용)
└── README.md
```

## 시작하기

### 전제 조건

- Docker 및 Docker Compose
- Python 3.11+

### 1. 설정

1.  **저장소 복제:**
    ```bash
    git clone <your-repo-url>
    cd webhook-service
    ```

2.  **환경 변수 구성:**
    예시 `.env` 파일을 `.env`로 복사하고 값을 채웁니다.
    ```bash
    cp .env.example .env
    ```
    - `DATABASE_URL`: 로컬 테스트를 위한 데이터베이스 URL (예: `sqlite:///./test.db`)
    - `GITHUB_WEBHOOK_SECRET`: GitHub 웹훅 설정의 비밀.
    - `STRIPE_WEBHOOK_SECRET`: Stripe 웹훅 서명 비밀.

### 2. 서비스 실행 (Docker - 권장)

전체 애플리케이션 스택(웹 서버, 워커, Redis)을 실행하는 가장 간단한 방법입니다.

```bash
docker-compose up --build -d
```

서비스를 시작한 후 데이터베이스 마이그레이션을 적용해야 합니다.

**데이터베이스 마이그레이션 적용 (Docker 컨테이너 내부):**
```bash
docker-compose exec web alembic upgrade head
```

**프로덕션 배포:**

프로덕션 환경에서는 `docker-compose.prod.yml` 파일을 사용합니다. 자세한 내용은 `docs/deployment.md`를 참조하세요.

서비스는 다음 엔드포인트에서 사용할 수 있습니다.
- **애플리케이션**: `http://localhost:8000`
- **관리자 UI**: `http://localhost:8000/admin`
- **상태 확인**: `http://localhost:8000/health` (마이그레이션 후 `{"status": "ok"}`를 반환해야 함)
- **메트릭**: `http://localhost:8000/metrics`
- **API 문서**: `http://localhost:8000/8000/docs`

### 3. 로컬 개발 (Docker 없이)

1.  **가상 환경 생성:**
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```

2.  **종속성 설치:**
    ```bash
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
    ```

3.  **데이터베이스 마이그레이션 적용:**
    ```bash
    alembic upgrade head
    ```

4.  **서비스 실행** (별도의 터미널 창에서):
    ```bash
    # 터미널 1: Redis 실행 (Docker를 사용하지 않는 경우)
    # redis-server

    # 터미널 2: Celery 워커 실행
    celery -A app.celery_worker.celery worker --loglevel=info

    # 터미널 3: FastAPI 웹 서버 실행
    uvicorn app.main:app --reload
    ```

## 개발자 경험 (DX)

### 코드 품질

이 프로젝트는 린팅 및 포맷팅을 위해 `ruff`를 사용합니다. 커밋하기 전에 코드를 자동으로 포맷하려면 pre-commit 훅을 설정하세요.

```bash
# 개발 요구 사항 설치 후 한 번 실행
pre-commit install
```

### 테스트 실행

통합 테스트는 이제 `fastapi.testclient.TestClient`를 사용하며 동기식입니다.

전체 테스트 스위트를 실행하려면:

```bash
pytest
```

### 데이터베이스 마이그레이션

이 프로젝트는 Alembic을 사용하여 데이터베이스 스키마 변경을 관리합니다.

1.  **`app/models/`에서 모델을 변경한 후 새 마이그레이션을 생성하려면:**
    ```bash
    alembic revision --autogenerate -m "변경에 대한 설명 메시지"
    ```

2.  **데이터베이스에 마이그레이션을 적용하려면:**
    ```bash
    alembic upgrade head
    ```

## Prometheus를 이용한 모니터링

서비스는 `prometheus-fastapi-instrumentator`를 사용하여 `/metrics` 엔드포인트에서 Prometheus 메트릭을 노출합니다.

Prometheus가 이러한 메트릭을 스크랩하도록 구성하려면:

1.  **`webhook-service`가 실행 중인지 확인** (예: `docker-compose up -d`를 통해).
2.  **`monitoring/prometheus.yml` 구성:**
    `prometheus.yml` 파일에 다음 `scrape_config`를 추가합니다. `web` 서비스 이름은 Docker 네트워크 내에서 대상 호스트로 사용됩니다.

    ```yaml
    # monitoring/prometheus.yml (예시 스니펫)
    scrape_configs:
      - job_name: 'webhook-service'
        static_configs:
          - targets: ['web:80'] # 'web'은 docker-compose.yml의 서비스 이름, 80은 내부 컨테이너 포트
    ```
    *(참고: 제공된 `monitoring/prometheus.yml`에는 이미 이 구성이 포함되어 있습니다.)*

3.  **Prometheus 재시작** (이미 실행 중인 경우)하여 구성 변경 사항을 적용합니다.
    ```bash
    docker-compose restart prometheus
    ```

4.  **Prometheus UI에서 확인:**
    브라우저를 `http://localhost:9090` (Prometheus UI)으로 열고 "Status" -> "Targets"로 이동합니다. `webhook-service`가 "UP"으로 표시되어야 합니다.