# CaseTally Backend Service

API microservice for legal search, code browsing, and streaming search delivery.

## Service Summary

- Service name: `casetally-backend`
- Runtime: FastAPI + Uvicorn (Python 3.11)
- Primary responsibility: Serve search APIs over HTTP and stream incremental search responses.
- Data dependency: PostgreSQL (`casetally_law`) with `legal_chunks` and `legal_artifacts`.
- Current maturity: Prototype (hybrid search endpoint is implemented; browse/stream/highlight APIs are pending).

## Responsibilities

This service owns:

- Search request validation and API contracts
- BM25 lexical retrieval against `legal_chunks.search_vector`
- Vector retrieval against `legal_chunks.embedding`
- Score fusion for hybrid ranking
- Result shaping for UI/mobile clients
- Health endpoints for platform orchestration

This service does not own:

- Source ingestion and scraping
- Re-embedding job orchestration
- PDF extraction pipeline

## Current API Surface

| Method | Path | Description | Status |
|---|---|---|---|
| GET | `/health/live` | Liveness probe | Implemented |
| GET | `/health/ready` | Readiness probe | Implemented |
| POST | `/v1/search` | Hybrid search (non-streaming) | Implemented |

## Planned API Surface

| Method | Path | Description | Priority |
|---|---|---|---|
| GET | `/v1/meta/version` | Build/version info | High |
| GET | `/v1/meta/capabilities` | Feature capability flags | High |
| GET | `/v1/search/stream` | SSE streaming search for web | High |
| GET | `/v1/ws/search` | WebSocket streaming search for iOS | High |
| GET | `/v1/codes/us/titles` | US code browse root | High |
| GET | `/v1/codes/us/titles/{title_number}` | US title detail | High |
| GET | `/v1/codes/us/sections/{section_id}` | US section detail | High |
| GET | `/v1/codes/states` | State list | High |
| GET | `/v1/codes/states/{state_code}/titles` | State title list | High |
| GET | `/v1/codes/states/{state_code}/sections/{section_id}` | State section detail | High |
| POST | `/v1/highlights` | Highlight generation request | Medium |
| GET | `/v1/highlights/{highlight_id}` | Highlight job status/result | Medium |
| GET | `/v1/artifacts/{artifact_id}` | Artifact metadata | Medium |
| GET | `/v1/artifacts/{artifact_id}/content` | Artifact stream/signed URL | Medium |

## Search Behavior (Implemented)

`POST /v1/search` pipeline:

1. Validate request and normalize weights.
2. BM25 retrieval using `plainto_tsquery('english', :query)` and `ts_rank_cd`.
3. Vector retrieval using pgvector cosine distance (`embedding <=> query_vector`).
4. Score normalization + weighted fusion into `hybrid_score`.
5. Attach best-effort primary artifact metadata from `legal_artifacts`.
6. Return ranked result list and query telemetry (`took_ms`, `embedding_used`).

## Data Contracts

Current request schema (simplified):

```json
{
  "query": "freedom of speech",
  "jurisdiction": "Federal",
  "document_type": "US Code",
  "top_k": 10,
  "bm25_k": 50,
  "vector_k": 50,
  "weight_bm25": 0.5,
  "weight_vector": 0.5
}
```

Current result fields:

- `chunk_id`
- `citation`
- `clause_id`
- `title`
- `snippet`
- `text_content`
- `jurisdiction`
- `document_type`
- `tags`
- `bm25_score`
- `vector_score`
- `hybrid_score`
- `artifact`

## Runtime Dependencies

- Python packages in `requirements.txt`
- PostgreSQL with pgvector extension
- Sentence transformer model download (when vector search enabled)

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://casetally:strongpassword@localhost:5432/casetally_law` | DB connection string |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Query embedding model |
| `EMBEDDING_DEVICE` | `cpu` | Inference device |
| `SEARCH_EMBEDDING_ENABLED` | `true` | Enable/disable vector branch |

## Local Development

```bash
cd casetally-backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload
```

OpenAPI:

- Swagger UI: `http://localhost:3001/docs`
- OpenAPI JSON: `http://localhost:3001/openapi.json`
- ReDoc: `http://localhost:3001/redoc`

Smoke test:

```bash
curl http://localhost:3001/health/live
curl http://localhost:3001/health/ready
curl -X POST http://localhost:3001/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"first amendment","top_k":5}'
```

## Docker

Build:

```bash
docker build -t casetally-backend:latest .
```

Run:

```bash
docker run --rm -p 3001:3001 \
  -e DATABASE_URL=postgresql://casetally:strongpassword@host.docker.internal:5432/casetally_law \
  casetally-backend:latest
```

## Container Registry Workflow

Tag and push:

```bash
docker tag casetally-backend:latest <REGISTRY>/<NAMESPACE>/casetally-backend:<TAG>
docker push <REGISTRY>/<NAMESPACE>/casetally-backend:<TAG>
```

Pull and run:

```bash
docker pull <REGISTRY>/<NAMESPACE>/casetally-backend:<TAG>
docker run -d --name casetally-backend -p 3001:3001 \
  -e DATABASE_URL=<DATABASE_URL> \
  <REGISTRY>/<NAMESPACE>/casetally-backend:<TAG>
```

## Observability and Operations

- Current logging: process logs via Python `logging`.
- Current health model: static `live` and `ready` responses.
- Required next hardening:
- request IDs
- structured JSON logs
- latency histograms
- endpoint-level rate limits
- authn/authz

## Known Gaps

- No SSE endpoint yet.
- No WebSocket endpoint yet.
- No browse endpoints for US/state code pages yet.
- No highlight artifact generation API yet.
- Readiness endpoint does not currently validate DB query health.

## Code Map

- `app/main.py`: app initialization and health routes
- `app/api/search.py`: search API route
- `app/services/search.py`: hybrid retrieval logic
- `app/schemas.py`: request/response models
- `app/db.py`: SQLAlchemy engine/session
