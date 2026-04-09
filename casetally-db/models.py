# backend/app/models/document.py
from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, Boolean, ForeignKey, Date, ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from __init__ import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(200))
    role = Column(String(50), default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())



class LegalChunk(Base):
    __tablename__ = "legal_chunks"

    id = Column(Integer, primary_key=True, index=True)
    citation = Column(String(200), nullable=False, index=True)
    clause_id = Column(String(250), unique=True, nullable=False)
    text_content = Column(Text, nullable=False)
    embedding = Column(Vector(384))
    jurisdiction = Column(String(100), default='Federal')
    document_type = Column(String(50))
    chunk_type = Column(String(50))
    tags = Column(ARRAY(Text))
    version_hash = Column(String(64), nullable=False)
    is_current = Column(Boolean, default=True)
    effective_date = Column(Date)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

class LegalArtifact(Base):
    __tablename__ = "legal_artifacts"
    
    id = Column(Integer, primary_key=True)
    citation = Column(String(200), nullable=False, index=True)
    artifact_type = Column(String(50), nullable=False)
    artifact_metadata = Column(JSONB, nullable=False)
    version_hash = Column(String(64), nullable=False)
    is_primary = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

class SearchQuery(Base):
    __tablename__ = "search_queries"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    query_text = Column(Text, nullable=False)
    search_type = Column(String(50))
    results_count = Column(Integer)
    execution_time_ms = Column(Integer)
    created_at = Column(TIMESTAMP, server_default=func.now())
    filters = Column(JSONB)

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String(200), nullable=False)
    message = Column(Text)
    notification_type = Column(String(50))
    is_read = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    notification_metadata = Column(JSONB)

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    
    id = Column(Integer, primary_key=True)
    source_type = Column(String(50), nullable=False)
    jurisdiction = Column(String(100))
    run_started_at = Column(TIMESTAMP, server_default=func.now())
    run_completed_at = Column(TIMESTAMP)
    status = Column(String(20))
    last_hash = Column(String(64))
    chunks_added = Column(Integer, default=0)
    chunks_updated = Column(Integer, default=0)
    artifacts_added = Column(Integer, default=0)
    error_message = Column(Text)
