from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    celery_broker_url: str
    celery_result_backend: str
    github_webhook_secret: str
    stripe_webhook_secret: str

    # Add the missing fields from the validation error
    gemini_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    google_cloud_project: Optional[str] = None
    postgres_db: Optional[str] = None
    postgres_user: Optional[str] = None
    postgres_password: Optional[str] = None
    admin_username: Optional[str] = None
    admin_password: Optional[str] = None


    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "webhook-service"
    keycloak_client_id: str = "webhook-admin-client"
    keycloak_client_secret: Optional[str] = None
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
