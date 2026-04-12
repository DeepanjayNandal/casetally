# CaseTally Embedding Worker Service

Background worker microservice for generating vector embeddings.

## Service Summary

- Service name: `casetally-workers`
- Runtime: Python worker loop + Redis state publishing
- Primary responsibility: Find unembedded text chunks, generate embeddings, persist vectors.
- Current maturity: Functional for legacy schema; not yet migrated to current citation-centric schema.

## Critical Compatibility Note

Current worker code reads/writes legacy table `document_chunks` via `shared/models_chunk.py`.

Current platform schema is citation-centric (`legal_chunks`, `legal_artifacts`).

Result: this worker is not production-compatible with the current DB schema until migration is completed.

## Responsibilities

This service owns:

- Polling DB for records with `embedding IS NULL`
- Batch embedding generation via sentence-transformers
- Persisting vectors to DB
- Worker lifecycle state publishing to Redis
- Heartbeat and metrics emission

This service does not own:

- Chunk creation or ingestion
- API request handling
- Hybrid ranking logic

## Runtime Dependencies

- PostgreSQL (legacy `document_chunks` model expected)
- Redis (state + metrics + heartbeat keys)
- sentence-transformers runtime model download

## Worker Lifecycle

States emitted to Redis:

- `starting`
- `loading_model`
- `idle`
- `processing`
- `error`
- `stopping`
- `stopped`

## Redis Keys

- `worker:embedding:{worker_id}:state`
- `worker:embedding:{worker_id}:metrics`
- `worker:embedding:{worker_id}:heartbeat`

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | none | PostgreSQL connection string |
| `REDIS_HOST` | No | `redis` | Redis host |
| `REDIS_PORT` | No | `6379` | Redis port |
| `BATCH_SIZE` | No | `100` | Rows per batch |
| `POLL_INTERVAL` | No | `5` | Idle poll wait seconds |
| `EMBEDDING_MODEL` | No | `sentence-transformers/all-MiniLM-L6-v2` | Model name |
| `EMBEDDING_DIMENSION` | No | `384` | Expected vector dimension |
| `EMBEDDING_DEVICE` | No | `cpu` | `cpu` or `cuda` |
| `HOSTNAME` | No | `embedding-worker-1` | Worker identifier |

## Local Run

```bash
cd casetally-workers
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
export DATABASE_URL="postgresql://user:password@localhost:5432/casetally"
export REDIS_HOST="localhost"
python embedding_worker.py
```

## Docker Run

Build:

```bash
docker build -t casetally-embedding-worker:latest .
```

Run:

```bash
docker run -d --name casetally-embedding-worker \
  -e DATABASE_URL="postgresql://user:password@db:5432/casetally" \
  -e REDIS_HOST="redis" \
  --network casetally-network \
  casetally-embedding-worker:latest
```

## Monitoring and Diagnostics

Heartbeat check:

```bash
redis-cli GET "worker:embedding:embedding-worker-1:heartbeat"
```

State check:

```bash
redis-cli GET "worker:embedding:embedding-worker-1:state"
```

## Current Gaps

- Uses legacy ORM model `DocumentChunk` with table `document_chunks`.
- References legacy FK to `legal_documents.id`.
- Not aligned with ingestion output in `legal_chunks`.

## Required Migration to Current Schema

1. Replace ORM model with `legal_chunks` mapping.
2. Fetch pending rows via `legal_chunks.embedding IS NULL AND is_current = TRUE`.
3. Use `text_content` instead of `content`.
4. Keep dimension configurable for current embedding model.
5. Validate with non-empty `legal_chunks` corpus after ingestion.

## Code Map

- `embedding_worker.py`: main worker loop and batching
- `embedding_service.py`: model load + batch embeddings
- `state_manager.py`: Redis state/metrics/heartbeat
- `shared/models_chunk.py`: legacy ORM mapping (migration target)
- `Dockerfile`: container image build
- `requirements.txt`: worker dependencies
