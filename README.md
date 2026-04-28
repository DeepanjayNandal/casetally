# CaseTally

A legal research platform for searching U.S. statutes, codes, and regulations using hybrid search and LLM-powered answers.

**Live demo:** _coming soon_

---

## What It Does

Ask any legal question in plain English. CaseTally rewrites your question into legal terminology, searches 33,969 U.S. Code chunks using hybrid BM25 + vector search, and streams a cited answer back in real time.

> "Can my boss fire me?" → rewrites to → "wrongful termination at-will employment exceptions" → retrieves exact statutes → streams grounded answer

---

## System Architecture

```
Browser
  │
  ├─ GET  /                    Next.js frontend (port 3000)
  ├─ POST /v1/chat/stream  ──► FastAPI backend (port 3001)
  └─ POST /v1/search       ──► FastAPI backend (port 3001)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              Query Rewrite    Hybrid Search    Groq API
              (Groq API)       (PostgreSQL)     (LLM stream)
                                    │
                           ┌────────┴────────┐
                           ▼                 ▼
                         BM25            pgvector
                       tsvector       HNSW cosine sim
                           └────────┬────────┘
                                    ▼
                             Score fusion
                             (hybrid_score)
                                    ▲
                          EmbeddingWorker
                          (offline, Redis-tracked)
```

---

## Request Flow

```
1. User types: "what happens if i dont pay taxes"

2. Query Rewriting (Groq, non-streaming)
   └─ Rewrites to: "tax debt collection unpaid tax penalties tax lien 26 usc 6851"

3. Hybrid Search (PostgreSQL)
   ├─ BM25:   ts_rank_cd(search_vector, plainto_tsquery(...))   top 30
   ├─ Vector: embedding <=> query_vector  [HNSW index]          top 30
   ├─ Normalize scores 0→1 independently
   └─ Fuse:   hybrid_score = 0.5*bm25 + 0.5*vector → top 3

4. LLM Answer (Groq, streaming)
   ├─ Top 3 chunk snippets sent as context
   ├─ llama-3.1-8b-instant generates cited answer
   └─ Tokens streamed via SSE → react-markdown renders live

5. Sources panel: separate /v1/search call (top 10) renders
   source cards with relevance scores
```

---

## Services

### `casetally-frontend` — Next.js (port 3000)
- Search page with multi-turn chat, SSE token streaming, source cards
- Browse U.S. Code page — 3-panel layout with `LegalTextRenderer` parsing `(a)(b)(1)(A)` statute structure
- Homepage with sample queries, stats bar, how-it-works section
- Runs locally via `npm run dev` (not in Docker)

### `casetally-backend` — FastAPI (port 3001)
- `POST /v1/chat/stream` — query rewrite → hybrid search → SSE-streamed LLM answer
- `POST /v1/search` — hybrid search only, returns ranked chunks with scores
- `GET /health/ready` — liveness + real DB ping
- Query rewriting via `GroqService.rewrite_query()` before every retrieval

### `casetally-db` — PostgreSQL 16 + pgvector
- `legal_chunks` table — 33,969 rows, each with `text_content`, `search_vector` (tsvector), `embedding` (vector(384))
- HNSW index on `embedding` column for sub-linear ANN lookup
- GIN index on `search_vector` for BM25
- Triggers auto-update `search_vector` on insert/update

### `casetally-workers` — Embedding Worker
- Polls `legal_chunks WHERE embedding IS NULL`
- Batch encodes via `sentence-transformers/all-MiniLM-L6-v2` on CPU
- Writes 384-dim vectors back to DB
- State tracked in Redis (IDLE → PROCESSING → IDLE)

### `casetally-ingestion` — Ingestion CLI
- Parses govinfo.gov XML for all 54 U.S. Code titles
- Chunks text (~500 tokens), writes to `legal_chunks`
- One-time run to populate the database

### `casetally-infrastructure` — Docker Compose configs
- `docker-compose.local.yml` — full local stack
- `docker-compose.prod.yml` — production stack with Traefik reverse proxy

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript |
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 |
| Database | PostgreSQL 16 + pgvector |
| Search | Hybrid BM25 + vector, HNSW indexing |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2, 384-dim) |
| LLM | Groq API (llama-3.1-8b-instant) |
| Cache | Redis (worker state) |
| Data source | govinfo.gov XML — 54 U.S. Code titles |

---

## Key Technical Decisions

**Why hybrid search?**
Legal text has precise terminology — `§ 1983`, `habeas corpus`, `mens rea`. BM25 catches exact statute numbers that semantic search misses. Vector search catches meaning when phrasing differs. Fusion beats either alone.

**Why query rewriting?**
User language and legal language don't match. "Can my boss fire me?" contains none of the words in the statutes that answer it. Rewriting to "wrongful termination at-will employment" before retrieval dramatically improves BM25 recall.

**Why HNSW over ivfflat?**
HNSW (Hierarchical Navigable Small World) provides better recall, handles inserts without retraining, and is what production vector databases (Pinecone, Weaviate, Qdrant) use internally. Replaced ivfflat after initial ingestion.

**Why SSE over WebSocket?**
Token streaming is one-directional (server → client). SSE is HTTP-native, auto-reconnects, and works through proxies — no overhead of a persistent bidirectional socket.

**Why PostgreSQL for vectors instead of a dedicated vector DB?**
Single database keeps BM25 and vector search in one query with no cross-service joins. pgvector on PostgreSQL covers both at zero extra cost or infrastructure complexity.

---

## Local Setup

### Prerequisites
- Docker and Docker Compose
- Node.js 18+
- Groq API key (free at console.groq.com)

### Run

```bash
cp .env.local.example .env.local
# Add your GROQ_API_KEY to .env.local

# Start backend, postgres, redis
docker compose -f docker-compose.local.yml --env-file .env.local up -d

# Start frontend
cd casetally-frontend && npm install && npm run dev
```

Frontend: http://localhost:3000
Backend: http://localhost:3001
API docs: http://localhost:3001/docs

### Ingest data (one-time)

```bash
docker compose -f docker-compose.local.yml run --rm ingestion python cli.py --source uscode
```

---

## Deployment

| Service | Platform |
|---|---|
| Frontend | Vercel |
| Backend | Render |
| Database | Supabase (PostgreSQL + pgvector) |
| Redis | Upstash |
| LLM | Groq (free tier) |

---

## License

MIT
