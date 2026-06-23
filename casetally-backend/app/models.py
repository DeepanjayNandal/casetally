from sqlalchemy import TIMESTAMP, Boolean, Column, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class LegalArtifact(Base):
    __tablename__ = "legal_artifacts"

    id = Column(Integer, primary_key=True)
    citation = Column(String(200), nullable=False)
    artifact_type = Column(String(50), nullable=False)
    artifact_metadata = Column(JSONB, nullable=False)
    version_hash = Column(String(64), nullable=False)
    is_primary = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
