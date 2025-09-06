# Production-Ready Webhook Service

[![CI](https://github.com/<your-github-username>/<your-repo-name>/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-github-username>/<your-repo-name>/actions/workflows/ci.yml)

This project is a robust, scalable, and production-ready webhook processing service built with Python, FastAPI, Celery, and SQLAlchemy.

## Features

- **Multi-Provider Support**: Easily extensible to support webhooks from any provider (e.g., GitHub, Stripe).
- **Secure**: Validates incoming webhooks using signature verification (HMAC-SHA256).
- **Reliable Background Processing**: Uses Celery and Redis to queue and process webhooks asynchronously, preventing data loss and API timeouts.
- **Automatic Retries**: Failed webhook processing jobs are automatically retried with exponential backoff.
- **Database Persistence**: All incoming events are logged to a database (SQLite/PostgreSQL) for auditing and replay.
- **Database Migrations**: Uses Alembic to manage database schema changes safely.
- **Admin UI**: A web interface at `/admin` to view, search, and manage received webhook events.
- **Event Replay**: An API endpoint to re-queue and re-process any event from the database.
- **Observability**: 
    - Structured JSON logging for easy analysis.
    - `/health` endpoint for service status checks.
    - `/metrics` endpoint for Prometheus monitoring.
- **Automated DX**: Comes with `ruff` for linting/formatting, `pre-commit` hooks for quality control, and a CI pipeline via GitHub Actions.

## Architecture

- **Web Framework**: FastAPI
- **Background Jobs**: Celery
- **Message Broker**: Redis
- **Database**: SQLAlchemy (with support for SQLite and PostgreSQL)
- **DB Migrations**: Alembic
- **Admin UI**: SQLAdmin

### Directory Structure
```
/webhook-service/
├── alembic/               # Database migration scripts
├── app/                   # Main application code
│   ├── services/          # Business logic (Celery tasks)
│   ├── models/            # SQLAlchemy DB models
│   ├── schemas/           # Pydantic schemas
│   ├── dependencies.py    # FastAPI dependencies (e.g., verifiers)
│   ├── webhook_registry.py # Logic for registering new webhook sources
│   ├── main.py            # FastAPI app, endpoints
│   └── ...
├── tests/                 # Integration and unit tests
├── .github/workflows/     # CI pipeline (GitHub Actions)
├── .env.example           # Environment variable template
├── docker-compose.yml     # Docker services definition
├── Dockerfile             # Docker image definition
├── pyproject.toml         # Project config (for ruff)
└── README.md
```

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Python 3.11+

### 1. Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd webhook-service
    ```

2.  **Configure environment variables:**
    Copy the example `.env` file and fill in your secrets.
    ```bash
    cp .env.example .env
    ```
    - `GITHUB_WEBHOOK_SECRET`: Your secret from the GitHub webhook settings.
    - `STRIPE_WEBHOOK_SECRET`: Your webhook signing secret from Stripe.

### 2. Running the Service (Docker - Recommended)

This is the simplest way to run the entire application stack (web server, worker, and Redis).

```bash
docker-compose up --build -d
```

After starting the services, you need to apply database migrations.

**Apply Database Migrations (inside Docker container):**
```bash
docker-compose exec web alembic upgrade head
```

The service will be available at the following endpoints:
- **Application**: `http://localhost:8000`
- **Admin UI**: `http://localhost:8000/admin`
- **Health Check**: `http://localhost:8000/health` (Should return `{"status": "ok"}` after migrations)
- **Metrics**: `http://localhost:8000/metrics`
- **API Docs**: `http://localhost:8000/docs`

### 3. Local Development (Without Docker)

1.  **Create a virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
    ```

3.  **Apply database migrations:**
    ```bash
    alembic upgrade head
    ```

4.  **Run the services** (in separate terminal windows):
    ```bash
    # Terminal 1: Run Redis (if not using Docker)
    # redis-server

    # Terminal 2: Run the Celery worker
    celery -A app.celery_worker.celery worker --loglevel=info

    # Terminal 3: Run the FastAPI web server
    uvicorn app.main:app --reload
    ```

## Developer Experience (DX)

### Code Quality

This project uses `ruff` for linting and formatting. To automatically format your code before committing, set up the pre-commit hooks.

```bash
# Run this once after installing dev requirements
pre-commit install
```

### Running Tests

Integration tests now use `fastapi.testclient.TestClient` and are synchronous.

To run the full test suite:

```bash
pytest
```

### Database Migrations

This project uses Alembic to manage database schema changes.

1.  **To create a new migration after changing a model in `app/models/`:**
    ```bash
    alembic revision --autogenerate -m "A descriptive message for the change"
    ```

2.  **To apply migrations to the database:**
    ```bash
    alembic upgrade head
    ```

## Monitoring with Prometheus

The service exposes Prometheus metrics at the `/metrics` endpoint using `prometheus-fastapi-instrumentator`.

To configure Prometheus to scrape these metrics:

1.  **Ensure `webhook-service` is running** (e.g., via `docker-compose up -d`).
2.  **Configure `monitoring/prometheus.yml`**:
    Add the following `scrape_config` to your `prometheus.yml` file. The `web` service name is used as the target host within the Docker network.

    ```yaml
    # monitoring/prometheus.yml (example snippet)
    scrape_configs:
      - job_name: 'webhook-service'
        static_configs:
          - targets: ['web:80'] # 'web' is the service name in docker-compose.yml, 80 is the internal container port
    ```
    *(Note: The provided `monitoring/prometheus.yml` already contains this configuration.)*

3.  **Restart Prometheus** (if already running) to pick up configuration changes:
    ```bash
    docker-compose restart prometheus
    ```

4.  **Verify in Prometheus UI**:
    Open your browser to `http://localhost:9090` (Prometheus UI) and navigate to "Status" -> "Targets". You should see `webhook-service` listed as "UP".