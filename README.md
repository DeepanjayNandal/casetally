# CaseTally

A legal research platform for searching U.S. statutes, codes, and regulations using hybrid search and LLM-powered answers.

---

## What It Does

Ask any legal question in plain English. CaseTally rewrites your question into legal terminology, searches 83,706 U.S. Code chunks using hybrid BM25 + vector search, and streams a cited answer back in real time.

> "Can my boss fire me?" → rewrites to → "wrongful termination at-will employment exceptions" → retrieves exact statutes → streams grounded answer

---

## System Architecture

```text
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

```text
1. User types: "what happens if i dont pay taxes"

2. Query Rewriting (Groq, non-streaming)
   └─ Rewrites to: "tax debt collection unpaid tax penalties tax lien 26 usc 6851"

3. Hybrid Search (PostgreSQL)
   ├─ BM25:   ts_rank_cd(search_vector, plainto_tsquery(...))   top 50
   ├─ Vector: embedding <=> query_vector  [HNSW index]          top 50
   ├─ Normalize scores 0→1 independently
   └─ Fuse:   hybrid_score = 0.5*bm25 + 0.5*vector → top 3

4. LLM Answer (Groq, streaming)
   ├─ Top 3 chunk snippets sent as context
   ├─ openai/gpt-oss-20b generates cited answer
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
- `POST /v1/search` — hybrid search only, p50 18ms retrieval across 83k+ chunks
- `POST /v1/rewrite` — exposes query rewriting as a standalone endpoint
- `GET /health/ready` — liveness + real DB ping
- Query rewriting via `GroqService.rewrite_query()` before every retrieval

### `casetally-db` — PostgreSQL 16 + pgvector

- `legal_chunks` table — 83,706 rows, each with `text_content`, `search_vector` (tsvector), `embedding` (vector(384))
- HNSW index on `embedding` column for sub-linear ANN lookup
- GIN index on `search_vector` for BM25
- Triggers auto-update `search_vector` on insert/update

### `casetally-workers` — Embedding Worker

- Polls `legal_chunks WHERE embedding IS NULL`
- Batch encodes via `sentence-transformers/all-MiniLM-L6-v2` on CPU
- Writes 384-dim vectors back to DB in a single bulk executemany call
- State tracked in Redis (IDLE → PROCESSING → IDLE) with heartbeat

### `casetally-ingestion` — Ingestion CLI

- Custom section-by-section HTML parser across govinfo.gov files for all 53 existing U.S. Code titles (Title 53 is reserved and has no content), extracting section structure and cross-referencing PDF page offsets from embedded markup comments
- Chunks text by section, writes to `legal_chunks`
- Idempotent: SHA256 version hash per section — re-runs skip unchanged content, update changed content, and reset embeddings only when text changes
- Stale-chunk deactivation runs once per citation at the end of a run, using the union of every `clause_id` seen, so a citation appearing as multiple section headings cannot retire the chunks written by its own earlier occurrence
- Verified corpus-wide: a full re-run across all 53 titles skips all 50,915 sections with 0 inserts, 0 updates, and 0 deactivations, leaving the database unchanged

### `casetally-infrastructure` — Docker Compose configs

- `docker-compose.local.yml` — full local stack
- `docker-compose.prod.yml` — production stack with Traefik reverse proxy

---

## Stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript |
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 |
| Database | PostgreSQL 16 + pgvector |
| Search | Hybrid BM25 + vector, HNSW indexing |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2, 384-dim) |
| LLM | Groq API (openai/gpt-oss-20b) |
| Cache | Redis (worker state) |
| Data source | govinfo.gov HTML — 53 U.S. Code titles |

---

## Key Technical Decisions

**Why hybrid search?**
Legal text has precise terminology — `§ 1983`, `habeas corpus`, `mens rea`. BM25 catches exact statute numbers that semantic search misses. Vector search catches meaning when phrasing differs. Fusion beats either alone.

**Why query rewriting?**
User language and legal language don't match. "Can my boss fire me?" contains none of the words in the statutes that answer it, and rewrites to "termination rights employee termination unlawful dismissal at-will employment" before retrieval. Measured effect is a trade-off: MRR improves 10% while Precision@3 and Recall@5 drop slightly, so the right statute ranks higher but the top-5 window gets noisier.

**Why HNSW over ivfflat?**
HNSW (Hierarchical Navigable Small World) provides better recall, handles inserts without retraining, and is what production vector databases (Pinecone, Weaviate, Qdrant) use internally. Replaced ivfflat after initial ingestion.

**Why SSE over WebSocket?**
Token streaming is one-directional (server → client). SSE is HTTP-native, auto-reconnects, and works through proxies — no overhead of a persistent bidirectional socket.

**Why PostgreSQL for vectors instead of a dedicated vector DB?**
Single database keeps BM25 and vector search in one query with no cross-service joins. pgvector on PostgreSQL covers both at zero extra cost or infrastructure complexity.

---

## Evaluation

A retrieval evaluation harness lives in `scripts/eval_retrieval.py`. It runs 15 benchmark legal queries against the live search endpoint and measures:

- **Precision@3** — fraction of top-3 results from the correct U.S. Code title
- **Recall@5** — fraction of expected titles found in top-5 results
- **MRR** — mean reciprocal rank of the first relevant result

```bash
python scripts/eval_retrieval.py
python scripts/eval_retrieval.py --backend http://localhost:3001 --top-k 5 --rewrite
```

### Results (local instance, warm model, all 53 titles ingested)

Two modes: raw hybrid search, and hybrid search with LLM query rewriting (the actual user-facing flow).

| Metric | Without rewriting | With rewriting |
| --- | --- | --- |
| Mean Precision@3 | 0.67 | 0.62 |
| Mean Recall@5 | 0.76 | 0.69 |
| Mean MRR | 0.69 | 0.76 |
| p50 latency | 18ms | 33ms (incl. rewrite call) |
| p95 latency | 36ms | 45ms |

Query rewriting is a trade-off rather than a uniform gain. It improves MRR by 10% — the first
relevant statute ranks higher — while lowering Precision@3 and Recall@5, because the expanded
query pulls in more loosely-related neighbours across the top-5 window. For a product where the
user reads result one, MRR is the metric that matters.

**Effect of corpus coverage.** An earlier run against 22 of 53 titles (32,969 chunks) scored
P@3 0.31, R@5 0.34, MRR 0.39. Seven benchmark queries scored 0.00 purely because their titles
were absent. Ingesting the remaining 31 titles more than doubled every metric, and latency
*improved* despite 2.5x the data, since HNSW lookup is sub-linear in corpus size.

**A query that still fails.** "Wire fraud criminal penalties" scores 0.00 in both modes even
though `18 U.S.C. § 1343` is present with correct text. Three factors compound: `plainto_tsquery`
requires every term to appear in a single chunk, 512-word chunking scatters the statute's terms
across chunks, and "wire fraud" is a colloquial label absent from statutory text that reads
"scheme or artifice to defraud" transmitted "by means of wire". The governing chunk contains
neither "criminal" nor any form of "penalty", so BM25 excludes it before ranking begins.

Full per-query output for both modes is committed to `scripts/eval_results.txt`.

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
| --- | --- |
| Frontend | Vercel |
| Backend | Render |
| Database | Supabase (PostgreSQL + pgvector) |
| Redis | Upstash |
| LLM | Groq (free tier) |

---

## License

MIT
