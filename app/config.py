from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    celery_broker_url: str
    celery_result_backend: str
    redis_url: str = "redis://localhost:6379/0"

    postgres_db: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    admin_username: str | None = None
    admin_password: str | None = None

    session_secret: str

    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "webhook-service"
    keycloak_client_id: str = "webhook-admin-client"
    keycloak_client_secret: str | None = None
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
