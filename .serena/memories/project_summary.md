# Project Summary

This is a production-ready webhook processing service built with Python.

## Key Features

- **Multi-Provider Support**: Can handle webhooks from various sources like GitHub and Stripe.
- **Secure**: Verifies incoming webhooks using HMAC-SHA256.
- **Asynchronous Processing**: Uses Celery and Redis for reliable background job processing.
- **Database Persistence**: Logs all events to a database (SQLite/PostgreSQL) using SQLAlchemy.
- **Admin UI**: Provides a web interface to manage webhook events.
- **Observability**: Includes structured logging, health checks, and Prometheus metrics.

## Tech Stack

- **Web Framework**: FastAPI
- **Background Jobs**: Celery
- **Message Broker**: Redis
- **Database**: SQLAlchemy, Alembic
- **Admin UI**: SQLAdmin
