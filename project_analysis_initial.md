# Initial Project Analysis

This document contains the initial analysis of the project based on the information stored by Serena MCP.

---

## Project Summary

This is a production-ready webhook processing service built with Python.

### Key Features

- **Multi-Provider Support**: Can handle webhooks from various sources like GitHub and Stripe.
- **Secure**: Verifies incoming webhooks using HMAC-SHA256.
- **Asynchronous Processing**: Uses Celery and Redis for reliable background job processing.
- **Database Persistence**: Logs all events to a database (SQLite/PostgreSQL) using SQLAlchemy.
- **Admin UI**: Provides a web interface to manage webhook events.
- **Observability**: Includes structured logging, health checks, and Prometheus metrics.

### Tech Stack

- **Web Framework**: FastAPI
- **Background Jobs**: Celery
- **Message Broker**: Redis
- **Database**: SQLAlchemy, Alembic
- **Admin UI**: SQLAdmin

---

## Style and Conventions

This project uses `ruff` for both linting and formatting to ensure consistent code style.

### Configuration (`pyproject.toml`)

- **Line Length**: 88 characters
- **Quote Style**: Double quotes (`"`)
- **Selected Lint Rules**: `E`, `F`, `W`, `I`, `UP`

### Pre-commit Hooks

The project uses `pre-commit` to automatically enforce style and quality checks before each commit. The configured hooks are:

- `trailing-whitespace`: Removes trailing whitespace.
- `end-of-file-fixer`: Ensures files end with a single newline.
- `check-yaml`: Checks YAML files for syntax errors.
- `check-added-large-files`: Prevents large files from being committed.
- `ruff`: Runs the linter with auto-fix enabled.
- `ruff-format`: Formats code according to the defined style.

To enable these hooks, run `pre-commit install` after setting up your environment.

---

## Suggested Commands

Here are the most important commands for developing in this project.

### Setup

1.  **Clone the repository**
    ```bash
    git clone <your-repo-url>
    cd webhook-service
    ```

2.  **Configure environment**
    ```bash
    cp .env.example .env
    ```

3.  **Create virtual environment and install dependencies**
    ```bash
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
    ```

4.  **Set up pre-commit hooks**
    ```bash
    pre-commit install
    ```

### Running the Application

#### With Docker (Recommended)

1.  **Start services**
    ```bash
    docker-compose up --build -d
    ```

2.  **Apply database migrations**
    ```bash
    docker-compose exec web alembic upgrade head
    ```

#### Locally (Without Docker)

1.  **Apply database migrations**
    ```bash
    alembic upgrade head
    ```

2.  **Run services in separate terminals**
    ```bash
    # Terminal 1: Celery Worker
    celery -A app.celery_worker.celery worker --loglevel=info

    # Terminal 2: FastAPI Server
    uvicorn app.main:app --reload
    ```

### Development Tasks

- **Run tests**
  ```bash
  pytest
  ```

- **Create a new database migration**
  ```bash
  alembic revision --autogenerate -m "Your migration message"
  ```

- **Apply database migrations**
  ```bash
  alembic upgrade head
  ```
