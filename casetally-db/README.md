# CaseTally Database Service

PostgreSQL + pgvector microservice for all CaseTally persistent data.

## Service Summary

- Service name: `casetally-db`
- Runtime: PostgreSQL 16 (image based on `ankane/pgvector`)
- Primary responsibility: store legal corpus, artifacts, and operational metadata.
- Schema style: citation-centric (`legal_chunks` + `legal_artifacts`).

## Responsibilities

This service owns:

- Core relational schema and indexes
- Vector storage for semantic retrieval
- Full-text search vectors for lexical retrieval
- Ingestion and query telemetry tables
- DB migrations via Alembic

This service does not own:

- Ingestion orchestration
- Embedding generation jobs
- HTTP APIs

## Runtime Components

- Postgres container: `casetally-postgres`
- Admin UI: `casetally-adminer`
- Default DB: `casetally_law`
- Default port: `5432`

## Local Startup

```bash
docker network create casetally-network
docker build -t localhost:5000/casetally-db:latest casetally-db
docker compose -f casetally-infrastructure/services/casetally-db/docker-compose.yml up -d
```

Verify:

```bash
docker ps
docker exec -it casetally-postgres psql -U casetally -d casetally_law -c "\\dt"
```

## Adminer Access

Adminer URL:

- `http://localhost:5051`

Login values:

- System: `PostgreSQL`
- Server: `casetally-postgres`
- Username: `casetally`
- Password: value of `POSTGRES_PASSWORD` in `casetally-infrastructure/services/casetally-db/.env`
- Database: `casetally_law`

## Schema Overview

Primary tables:

- `users`
- `legal_chunks`
- `legal_artifacts`
- `search_queries`
- `notifications`
- `ingestion_runs`

Important views/functions:

- `legal_search_results`
- `current_citations`
- `get_pdf_page(citation_text)`
- `check_version_consistency()`

Schema source of truth:

- `casetally-db/init.sql`
- `casetally-db/alembic/versions/001_initial_schema.py`

## Search-Critical Columns

`legal_chunks`:

- `embedding vector(384)` for semantic similarity
- `search_vector tsvector` for full-text ranking
- `citation`, `clause_id` for retrieval identity
- `version_hash`, `is_current` for legal-version control

`legal_artifacts`:

- `artifact_type` (`pdf`, `html`, `xml`, `api`)
- `artifact_metadata jsonb`
- `version_hash` alignment with `legal_chunks`

## Performance Indexes

Implemented in `init.sql`:

- IVFFlat index on `legal_chunks.embedding`
- GIN index on `legal_chunks.search_vector`
- GIN index on `legal_chunks.tags`
- B-tree indexes for citation, jurisdiction, document type, `is_current`

## Connection Strings

Host machine:

```text
postgresql://casetally:<POSTGRES_PASSWORD>@localhost:5432/casetally_law
```

From same Docker network:

```text
postgresql://casetally:<POSTGRES_PASSWORD>@casetally-postgres:5432/casetally_law
```

## Migration Workflow

Create migration:

```bash
docker exec -it casetally-postgres bash -lc "cd /app && alembic revision --autogenerate -m 'change description'"
```

Apply migration:

```bash
docker exec -it casetally-postgres bash -lc "cd /app && alembic upgrade head"
```

## Operational Queries

Vector example:

```sql
SELECT id, citation, embedding <=> '[0.1,0.2,...]'::vector AS distance
FROM legal_chunks
WHERE is_current = TRUE AND embedding IS NOT NULL
ORDER BY embedding <=> '[0.1,0.2,...]'::vector
LIMIT 10;
```

Lexical example:

```sql
SELECT id, citation, ts_rank_cd(search_vector, plainto_tsquery('english', 'first amendment')) AS score
FROM legal_chunks
WHERE is_current = TRUE
  AND search_vector @@ plainto_tsquery('english', 'first amendment')
ORDER BY score DESC
LIMIT 10;
```

## Backup and Restore (Recommended)

Backup:

```bash
docker exec -t casetally-postgres pg_dump -U casetally -d casetally_law > casetally_law.sql
```

Restore:

```bash
cat casetally_law.sql | docker exec -i casetally-postgres psql -U casetally -d casetally_law
```

## Known Constraints

- Embedding dimension currently set to `384` in schema.
- Any model change requiring different vector dimension needs DB migration + re-embedding.
- Legacy tables `legal_documents` / `document_chunks` are intentionally not part of current schema.

## File Map

- `init.sql`: baseline schema, triggers, indexes, views
- `models.py`: SQLAlchemy model definitions
- `alembic/`: migration scripts and environment
- `Dockerfile`: DB image build with init + migration tooling
- `requirements.txt`: Python tooling for migrations
