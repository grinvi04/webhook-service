from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"options": "-c timezone=utc"},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

_async_url = settings.database_url
if _async_url.startswith("postgresql+psycopg2://"):
    _async_url = _async_url.replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://", 1
    )
elif _async_url.startswith("postgresql://"):
    _async_url = _async_url.replace("postgresql://", "postgresql+asyncpg://", 1)
async_engine = create_async_engine(
    _async_url,
    connect_args={"server_settings": {"TimeZone": "UTC"}},
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session
