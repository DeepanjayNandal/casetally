import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.dependencies import groq_service, search_service
from app.errors import client_error, report
from app.schemas import SearchRequest, SearchResponse

router = APIRouter(prefix="/v1", tags=["search"])

logger = logging.getLogger(__name__)


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
        # Degrades to the original query rather than failing the request, so
        # nothing reaches the client and no id is needed. Logged because a
        # silent swallow made a broken Groq key look like a no-op rewrite.
        logger.warning("rewrite failed, using the original query", exc_info=True)
        rewritten = payload.query
    return RewriteResponse(original=payload.query, rewritten=rewritten)


@router.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest, db: Session = Depends(get_db)):
    if payload.weight_bm25 == 0 and payload.weight_vector == 0:
        raise HTTPException(status_code=400, detail="At least one weight must be > 0")

    total_weight = payload.weight_bm25 + payload.weight_vector
    weight_bm25 = payload.weight_bm25 / total_weight if total_weight > 0 else 0.5
    weight_vector = payload.weight_vector / total_weight if total_weight > 0 else 0.5

    # Previously unguarded, so a database outage surfaced as Starlette's bare
    # 500 with nothing an operator could correlate. The response_model does not
    # apply to the error branch, which is why this returns a JSONResponse.
    try:
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
            # Lets the two retrieval branches run at the same time, each on its
            # own session. See HybridSearchService.search.
            session_factory=SessionLocal,
        )
    except Exception:
        error_id = report(logger, "search failed for %r", payload.query)
        return JSONResponse(
            status_code=503,
            content=client_error(
                "Search is temporarily unavailable. Please try again in a moment.",
                error_id,
            ),
        )
