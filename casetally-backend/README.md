# CaseTally Backend Service

API service for legal search and LLM-powered streaming answers.

## Service Summary

- Service name: `casetally-backend`
- Runtime: FastAPI + Uvicorn (Python 3.11)
- Primary responsibility: Query rewriting, hybrid search, and SSE-streamed LLM answers.
- Data dependency: PostgreSQL (`casetally_law`) with `legal_chunks` and `legal_artifacts`.

## Responsibilities

This service owns:

- Query rewriting — normalizes conversational questions into legal terminology before retrieval
- BM25 lexical retrieval against `legal_chunks.search_vector`
- Vector retrieval against `legal_chunks.embedding` (HNSW index)
- Score fusion for hybrid ranking
- LLM answer generation via Groq API with SSE token streaming
- Health endpoints for platform orchestration

This service does not own:

- Source ingestion and scraping
- Re-embedding job orchestration
- PDF extraction pipeline

## API Surface

| Method | Path | Description |
|---|---|---|
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe (checks DB connection) |
| POST | `/v1/search` | Hybrid search, returns ranked chunks |
| POST | `/v1/chat/stream` | Query rewrite → hybrid search → SSE-streamed LLM answer |

## Request Pipeline — `/v1/chat/stream`

1. Rewrite user query into legal terminology via Groq (`rewrite_query`)
2. BM25 retrieval using `plainto_tsquery` + `ts_rank_cd`
3. Vector retrieval using pgvector HNSW cosine distance (`embedding <=> query_vector`)
4. Score normalization + weighted fusion into `hybrid_score`
5. Top 3 chunks sent to Groq (`openai/gpt-oss-20b`) for answer generation
6. Tokens streamed back as SSE: `data: {"type": "text", "chunk": "..."}`

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://casetally:...@localhost:5432/casetally_law` | DB connection string |
| `GROQ_API_KEY` | — | Groq API key (required) |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Groq model for rewriting + answers |
| `GROQ_REASONING_EFFORT` | `low` | Reasoning budget for reasoning-class models; set empty to omit |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Query embedding model |
| `EMBEDDING_DEVICE` | `cpu` | Inference device |
| `SEARCH_EMBEDDING_ENABLED` | `true` | Enable/disable vector branch |

## Local Development

```bash
docker compose -f docker-compose.local.yml --env-file .env.local up backend -d --force-recreate
```

OpenAPI docs: `http://localhost:3001/docs`

Smoke test:

```bash
curl http://localhost:3001/health/ready
curl -X POST http://localhost:3001/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"first amendment","top_k":5}'
```

## Code Map

- `app/main.py` — app init, health routes
- `app/api/search.py` — search endpoint
- `app/routers/chat.py` — chat/stream endpoint, query rewriting orchestration
- `app/services/search.py` — hybrid BM25 + vector retrieval
- `app/services/groq_service.py` — query rewriting + LLM streaming
- `app/db.py` — SQLAlchemy engine/session
- `app/schemas.py` — request/response models
