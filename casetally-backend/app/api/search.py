from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import groq_service, search_service
from app.schemas import SearchRequest, SearchResponse

router = APIRouter(prefix="/v1", tags=["search"])


class RewriteRequest(BaseModel):
    query: str


class RewriteResponse(BaseModel):
    original: str
    rewritten: str


@router.post("/rewrite", response_model=RewriteResponse)
def rewrite(payload: RewriteRequest):
    if not groq_service.is_available():
        return RewriteResponse(original=payload.query, rewritten=payload.query)
    try:
        rewritten = groq_service.rewrite_query(payload.query)
    except Exception:
        rewritten = payload.query
    return RewriteResponse(original=payload.query, rewritten=rewritten)


@router.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest, db: Session = Depends(get_db)):
    if payload.weight_bm25 == 0 and payload.weight_vector == 0:
        raise HTTPException(status_code=400, detail="At least one weight must be > 0")

    total_weight = payload.weight_bm25 + payload.weight_vector
    weight_bm25 = payload.weight_bm25 / total_weight if total_weight > 0 else 0.5
    weight_vector = payload.weight_vector / total_weight if total_weight > 0 else 0.5

    return search_service.search(
        db=db,
        query=payload.query,
        top_k=payload.top_k,
        bm25_k=payload.bm25_k,
        vector_k=payload.vector_k,
        weight_bm25=weight_bm25,
        weight_vector=weight_vector,
        jurisdiction=payload.jurisdiction,
        document_type=payload.document_type,
    )
