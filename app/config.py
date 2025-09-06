from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    celery_broker_url: str
    celery_result_backend: str
    github_webhook_secret: str
    stripe_webhook_secret: str

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
