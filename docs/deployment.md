# Production Deployment Guide

This guide outlines the process for deploying the `webhook-service` to a production environment. This process leverages the production-ready Docker image built by our CI/CD pipeline and the `docker-compose.prod.yml` file.

## Prerequisites

*   A server or cluster with Docker and Docker Compose installed.
*   A configured `.env` file with all the necessary production secrets and configurations.
*   Access to the container registry where the production Docker image is stored.

## Secrets Management

**Important**: Using a plain-text `.env` file is suitable for development but is **not recommended for production** due to security risks.

For production environments, you should integrate with a dedicated secrets management service, such as:

*   **AWS Secrets Manager**
*   **Google Cloud Secret Manager**
*   **HashiCorp Vault**

These tools provide enhanced security, access control, and audit logging for your sensitive credentials.

To use a secrets manager, your deployment process should be configured to:
1.  Securely fetch secrets from the secrets manager during the deployment pipeline or at container startup.
2.  Inject these secrets as environment variables into the application containers (`web`, `worker`, etc.).

The application is designed to read its configuration from environment variables, so it will seamlessly use the secrets provided by the secrets manager without any code changes.

## Deployment Steps

1.  **Prepare the Environment**:
    *   Copy the `docker-compose.prod.yml` file to your deployment server.

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

## Scaling Out with Docker Swarm

For environments requiring high availability and horizontal scaling, you can deploy the service to a Docker Swarm cluster. Docker Swarm is a container orchestration tool built into Docker.

### 1. Setting Up the Swarm

You need at least one manager node and one or more worker nodes.

*   **On the manager node**, initialize the swarm:
    ```bash
    docker swarm init
    ```
*   **On each worker node**, join the swarm using the token provided by the `init` command.

### 2. Preparing for Deployment

The `docker-compose.prod.yml` file is mostly compatible with Docker Swarm. However, for a Swarm deployment, you should make a copy and remove the `build` context from the services, as Swarm expects pre-built images from a registry. Also, Swarm's networking will handle service discovery, so you don't need to expose all ports to the host.

### 3. Deploying the Stack

Use the `docker stack deploy` command to deploy your application stack to the swarm.

```bash
docker stack deploy -c docker-compose.prod.yml webhook-stack
```

### 4. Scaling Services

You can easily scale individual services to handle more traffic. For example, to scale the `web` service to 3 replicas and the `worker` service to 5 replicas:

```bash
docker service scale webhook-stack_web=3
docker service scale webhook-stack_worker=5
```

This setup provides redundancy and load balancing for your application, making it more resilient and scalable.
