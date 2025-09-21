from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import psycopg2 # Explicitly import psycopg2

from .config import settings

# Using synchronous engine for Celery tasks and Alembic
# The DATABASE_URL should now directly point to PostgreSQL
engine = create_engine(
    settings.database_url,
    connect_args={"options": "-c timezone=utc"}, # Ensure timezone is handled consistently
    pool_pre_ping=True # Ping database connections before use
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Using async engine for FastAPI is still possible if needed for other endpoints
# from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
# async_engine = create_async_engine(settings.database_url)
# AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

Base = declarative_base()


# Dependency for Celery tasks
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
