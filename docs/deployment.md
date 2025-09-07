# Production Deployment Guide

This guide outlines the process for deploying the `webhook-service` to a production environment. This process leverages the production-ready Docker image built by our CI/CD pipeline and the `docker-compose.prod.yml` file.

## Prerequisites

*   A server or cluster with Docker and Docker Compose installed.
*   A configured `.env` file with all the necessary production secrets and configurations.
*   Access to the container registry where the production Docker image is stored.

## Deployment Steps

1.  **Prepare the Environment**:
    *   Copy the `docker-compose.prod.yml` file to your deployment server.
    *   Create or copy the `.env` file to the same directory on the server and ensure it contains the correct production values.
    *   Make sure the `monitoring/prometheus.yml` file is also present if you are running the monitoring stack.

2.  **Pull the Latest Image**:
    *   Log in to your container registry.
    *   Pull the latest version of the application image.
    ```bash
    docker pull your-container-registry/webhook-service:latest
    ```

3.  **Start the Services**:
    *   Use the `docker-compose.prod.yml` file to start all the services in detached mode.
    ```bash
    docker-compose -f docker-compose.prod.yml up -d
    ```

4.  **Apply Database Migrations**:
    *   After starting the services, you must apply any pending database migrations.
    ```bash
    docker-compose -f docker-compose.prod.yml exec web alembic upgrade head
    ```

## Updating the Service

To update the service to a new version:

1.  **Pull the new image**:
    ```bash
    docker pull your-container-registry/webhook-service:latest
    ```
2.  **Re-create the services**:
    *   `docker-compose` will detect the new image and re-create only the services that have changed (in this case, `web` and `worker`).
    ```bash
    docker-compose -f docker-compose.prod.yml up -d
    ```
3.  **Apply Database Migrations** (if there are any schema changes in the new version):
    ```bash
    docker-compose -f docker-compose.prod.yml exec web alembic upgrade head
    ```
