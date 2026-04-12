# workers/embedding-worker/shared/models_chunk.py
import os
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, Boolean, Date, ARRAY
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()

# Embedding dimension should match the model being used
# Default: sentence-transformers/all-MiniLM-L6-v2 = 384 dimensions
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "384"))


class LegalChunk(Base):
    __tablename__ = "legal_chunks"

    id = Column(Integer, primary_key=True, index=True)
    citation = Column(String(200), nullable=False)
    clause_id = Column(String(250), unique=True, nullable=False)
    text_content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIMENSION))
    jurisdiction = Column(String(100))
    document_type = Column(String(50))
    chunk_type = Column(String(50))
    tags = Column(ARRAY(Text))
    version_hash = Column(String(64), nullable=False)
    is_current = Column(Boolean, default=True)
    effective_date = Column(Date)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())