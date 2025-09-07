# Suggested Commands

Here are the most important commands for developing in this project.

## Setup

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

## Running the Application

### With Docker (Recommended)

1.  **Start services**
    ```bash
    docker-compose up --build -d
    ```

2.  **Apply database migrations**
    ```bash
    docker-compose exec web alembic upgrade head
    ```

### Locally (Without Docker)

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

## Development Tasks

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
