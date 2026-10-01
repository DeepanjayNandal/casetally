import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.search import router as search_router
from app.db import SessionLocal
from app.dependencies import search_service
from app.routers.chat import router as chat_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the embedding model before uvicorn accepts any connection.

    The model is loaded lazily on first use, which under Kubernetes means a pod
    can pass its readiness probe and start receiving traffic while still cold,
    so the first real user pays the load cost. Doing it here closes that gap at
    the source: uvicorn does not bind until this function reaches its yield, so
    a cold process is never reachable at all.

    Warmup encodes one dummy string and nothing else. It must not touch
    Postgres or Groq, because startup would then depend on the database or an
    external API being up, turning an unrelated outage into pods that refuse to
    start.

    A failure here is logged and swallowed rather than fatal. Vector search is
    already designed to degrade to full-text-only when the model is
    unavailable, and a warmup failure is exactly that case.
    """
    try:
        search_service.embedding_service.warmup()
    except Exception:
        logger.exception("Embedding warmup failed; serving with full-text search only")
    yield


app = FastAPI(title="CaseTally Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health/live")
def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")
    return {"status": "ok"}


app.include_router(search_router)
app.include_router(chat_router)
