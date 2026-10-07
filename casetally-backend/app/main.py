import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.search import router as search_router
from app.db import SessionLocal
from app.dependencies import search_service
from app.errors import client_error, report
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
#
# The failure body used to be f"Database unavailable: {exc}", which put the
# driver, the Postgres host and the port into a response served through the
# ingress at /health/ready. The kubelet only reads the status code, so nothing
# needed that text; it is in the log instead, under the id the body carries.
@app.get("/health/ready")
def health_ready():
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception:
        error_id = report(logger, "readiness probe failed")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", **client_error("Database unavailable.", error_id)},
        )
    return {"status": "ok"}


# Last line of defence. Anything that reaches here is a bug rather than a
# handled condition, and Starlette's default would return the traceback only
# with debug on, but it would also return nothing an operator can correlate.
# This keeps the generic body and attaches the id that the log entry carries.
#
# Deliberately not registered for HTTPException: those are raised by this code
# with messages written for users, and masking them would turn a useful 400 or
# 404 into a mystery.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    error_id = report(logger, "unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=client_error(
            "Something went wrong on our side. Please try again.", error_id
        ),
    )


# search_router serves /v1/search and /v1/rewrite, chat_router serves
# /v1/chat/stream and the PDF artifact route. Both are mounted under /v1.
app.include_router(search_router)
app.include_router(chat_router)
