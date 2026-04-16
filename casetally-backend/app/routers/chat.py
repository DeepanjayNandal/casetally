import json
import logging
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import TIMESTAMP, Boolean, Column, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.db import SessionLocal, get_db
from app.services.groq_service import GroqService
from app.services.search import HybridSearchService

router = APIRouter(prefix="/v1", tags=["chat"])
search_service = HybridSearchService()
groq_service = GroqService()

logger = logging.getLogger(__name__)

_Base = declarative_base()


class LegalArtifact(_Base):
    __tablename__ = "legal_artifacts"

    id = Column(Integer, primary_key=True)
    citation = Column(String(200), nullable=False)
    artifact_type = Column(String(50), nullable=False)
    artifact_metadata = Column(JSONB, nullable=False)
    version_hash = Column(String(64), nullable=False)
    is_primary = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []


def _event(data: str) -> str:
    return f"data: {data}\n\n"


def _stream(query: str, history: List[Dict[str, Any]]):
    db = SessionLocal()
    try:
        results = search_service.search(
            db=db,
            query=query,
            top_k=3,
            bm25_k=30,
            vector_k=30,
            weight_bm25=0.5,
            weight_vector=0.5,
        )
        chunks = results["results"]

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
