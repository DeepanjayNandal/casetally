import json
import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.dependencies import groq_service, search_service
from app.models import LegalArtifact

router = APIRouter(prefix="/v1", tags=["chat"])

logger = logging.getLogger(__name__)

# How deep the sources panel shows, and how much of that the LLM reasons over.
# One retrieval serves both: the answer always sees the head of exactly the list
# the user is shown, so the two cannot disagree.
SOURCES_TOP_K = 10
ANSWER_TOP_K = 3


class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []


def _event(data: str) -> str:
    return f"data: {data}\n\n"


def _stream(query: str, history: List[Dict[str, Any]]):
    db = SessionLocal()
    try:
        # Rewrite query into legal terminology before retrieval.
        # Falls back to original if rewriting fails — never breaks the main flow.
        search_query = query
        if groq_service.is_available():
            try:
                rewritten = groq_service.rewrite_query(query)
                if rewritten and rewritten != query:
                    logger.info("query rewritten: %r -> %r", query, rewritten)
                    search_query = rewritten
            except Exception as exc:
                logger.warning("query rewriting failed, using original: %s", exc)

        # One retrieval, used for both the answer and the sources panel.
        #
        # The panel used to call /v1/search separately with the RAW question while
        # this endpoint searched the REWRITTEN one, at a different depth. Two
        # independent retrievals over two different query strings, so the panel
        # could display the correct statute while the answer, reasoning over a
        # different set, said it had no relevant information. That is not a
        # ranking bug, it is two answers to two different questions presented as
        # one result.
        #
        # Retrieve the panel's depth once and give the LLM the head of the same
        # list, so the answer is always reasoning over the top of exactly what the
        # user is shown.
        results = search_service.search(
            db=db,
            query=search_query,
            top_k=SOURCES_TOP_K,
            bm25_k=50,
            vector_k=50,
            weight_bm25=0.5,
            weight_vector=0.5,
        )
        sources = results["results"]
        chunks = sources[:ANSWER_TOP_K]

        # Emitted before the answer so the panel fills while tokens are still
        # streaming, and so it is populated even if the LLM call fails.
        yield _event(json.dumps({
            "type": "sources",
            "results": sources,
            "took_ms": results.get("took_ms"),
            "query": search_query,
            "embedding_used": results.get("embedding_used"),
        }))

        if groq_service.is_available() and chunks:
            try:
                for token in groq_service.stream_answer(query, chunks, history):
                    yield _event(json.dumps({"type": "text", "chunk": token}))
            except Exception as exc:
                logger.warning("Groq stream failed: %s", exc)
                yield _event(json.dumps({
                    "type": "text",
                    "chunk": "The AI assistant is temporarily unavailable. Please try again in a moment.",
                }))
        else:
            for result in chunks:
                yield _event(json.dumps({
                    "type": "text",
                    "chunk": f"{result['citation']}: {result['snippet']}",
                }))

        for result in chunks:
            if result.get("artifact"):
                artifact = result["artifact"]
                yield _event(json.dumps({
                    "type": "artifact",
                    "id": str(artifact["artifact_id"]),
                    "title": result["citation"],
                    "url": f"/v1/artifacts/{artifact['artifact_id']}/file",
                }))

        yield _event("[DONE]")
    finally:
        db.close()


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest):
    return StreamingResponse(
        _stream(payload.message, payload.history),
        media_type="text/event-stream",
    )


@router.get("/artifacts/{artifact_id}/file")
def get_artifact_file(artifact_id: int, db: Session = Depends(get_db)):
    artifact = db.query(LegalArtifact).filter(LegalArtifact.id == artifact_id).first()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    file_path = artifact.artifact_metadata.get("file_path", "")
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=500, detail="File not found on disk")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )
