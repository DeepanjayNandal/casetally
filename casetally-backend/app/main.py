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

    Uvicorn does not open its socket until this function reaches the yield, so a
    pod cannot pass its readiness probe while the model is still cold. Without
    this the first real user pays the load cost.

    Warmup encodes one dummy string and touches nothing else. It must not talk
    to Postgres or Groq, or an outage in either would stop pods from starting.

    A failure is logged and swallowed, not fatal: search already falls back to
    full-text only when the model is missing, which is exactly this case.
    """
    try:
        search_service.embedding_service.warmup()
    except Exception:
        logger.exception("Embedding warmup failed; serving with full-text search only")
    yield


app = FastAPI(title="CaseTally Backend", version="0.1.0", lifespan=lifespan)

# Wide open, and safe here only because of how this is served. Traefik puts the
# frontend and the API on one origin, so the browser never makes a cross-origin
# request and these headers are never used. If the API is ever hosted on its own
# domain, this needs a real allowlist.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Liveness: answers "is this process running", and deliberately checks nothing
# else. If it pinged the database, a brief Postgres outage would make Kubernetes
# restart every API pod, turning one failure into two.
@app.get("/health/live")
def health_live():
    return {"status": "ok"}


# Readiness: answers "should this pod get traffic", so it does check the
# database. A pod that cannot reach Postgres cannot answer a search, and
# returning 503 here takes it out of the Service until it can.
@app.get("/health/ready")
def health_ready():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")
    return {"status": "ok"}


# search_router serves /v1/search and /v1/rewrite, chat_router serves
# /v1/chat/stream and the PDF artifact route. Both are mounted under /v1.
app.include_router(search_router)
app.include_router(chat_router)
