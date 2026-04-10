# ingestion/core/db_utils.py
import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://casetally:casetally@localhost:5432/casetally_law"
)

# Create engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_ingestion_session() -> Session:
    """
    Get a database session for ingestion operations.

    Returns:
        SQLAlchemy Session object
    """
    session = SessionLocal()
    logger.info(f"Created database session (DB: {DATABASE_URL.split('@')[-1]})")
    return session


def get_db():
    """
    Dependency for FastAPI endpoints.

    Yields:
        SQLAlchemy Session object
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
