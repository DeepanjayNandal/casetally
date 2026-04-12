from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    jurisdiction: Optional[str] = None
    document_type: Optional[str] = None
    top_k: int = Field(default=10, ge=1, le=100)
    bm25_k: int = Field(default=50, ge=1, le=500)
    vector_k: int = Field(default=50, ge=1, le=500)
    weight_bm25: float = Field(default=0.5, ge=0.0, le=1.0)
    weight_vector: float = Field(default=0.5, ge=0.0, le=1.0)


class SearchResult(BaseModel):
    chunk_id: int
    citation: str
    clause_id: str
    title: str
    snippet: str
    text_content: str
    jurisdiction: Optional[str] = None
    document_type: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    bm25_score: float = 0.0
    vector_score: float = 0.0
    hybrid_score: float = 0.0
    artifact: Optional[Dict[str, Any]] = None


class SearchResponse(BaseModel):
    query: str
    total: int
    took_ms: int
    embedding_used: bool
    results: List[SearchResult]
