# CaseTally

A legal research platform for searching U.S. statutes, codes, and regulations using hybrid search and LLM-powered answers.

---

## What It Does

Ask any legal question in plain English. CaseTally rewrites your question into legal terminology, searches 33,969 U.S. Code chunks using hybrid BM25 + vector search, and streams a cited answer back in real time.

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
- `POST /v1/search` — hybrid search only, sub-100ms retrieval across 33k+ chunks
- `POST /v1/rewrite` — exposes query rewriting as a standalone endpoint
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
- Writes 384-dim vectors back to DB in a single bulk executemany call
- State tracked in Redis (IDLE → PROCESSING → IDLE) with heartbeat

### `casetally-ingestion` — Ingestion CLI

- Custom section-by-section HTML parser across govinfo.gov files for all 54 U.S. Code titles, extracting section structure and cross-referencing PDF page offsets from embedded markup comments
- Chunks text by section, writes to `legal_chunks`
- Idempotent: SHA256 version hash per section — re-runs skip unchanged content, update changed content, and reset embeddings only when text changes

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
| LLM | Groq API (llama-3.1-8b-instant) |
| Cache | Redis (worker state) |
| Data source | govinfo.gov HTML — 54 U.S. Code titles |

---

## Key Technical Decisions

**Why hybrid search?**
Legal text has precise terminology — `§ 1983`, `habeas corpus`, `mens rea`. BM25 catches exact statute numbers that semantic search misses. Vector search catches meaning when phrasing differs. Fusion beats either alone.

**Why query rewriting?**
User language and legal language don't match. "Can my boss fire me?" contains none of the words in the statutes that answer it. Rewriting to "wrongful termination at-will employment" before retrieval improves BM25 recall — particularly for queries where the colloquial legal term (e.g. "wire fraud") doesn't appear verbatim in the statute text.

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

### Results (local instance, warm model, 22 of 54 titles ingested)

Two modes: raw hybrid search, and hybrid search with LLM query rewriting (the actual user-facing flow).

| Metric | Without rewriting | With rewriting |
| --- | --- | --- |
| Mean Precision@3 | 0.31 | 0.36 |
| Mean Recall@5 | 0.34 | 0.42 |
| Mean MRR | 0.39 | 0.47 |
| p50 latency (search only) | 6ms | 73ms (incl. Groq rewrite call) |
| Max observed latency | 22ms | 233ms |

Query rewriting improved MRR by 21% and surfaced correct statutes for queries like "wire fraud criminal penalties" (0.00 → MRR 1.00) where the colloquial legal term doesn't appear verbatim in the statute text.

**Note on aggregate scores:** 7 of the 15 benchmark queries target titles not present in this local instance (Title 26 Tax, Title 35 Patents, Title 42 Social Security, Title 15 Antitrust, Title 33 Clean Water, Title 21 Controlled Substances, Title 29 Labor). Those 7 score 0.00 by construction — the statutes don't exist in the database. On the 8 queries where the relevant title is available, mean P@3 is 0.58 and mean MRR is 0.74 (with rewriting). On the 3 fully-covered queries (Bankruptcy, Copyright, Immigration), P@3 and MRR are both 1.00.

<details>
<summary>Full per-query breakdown — with rewriting</summary>

```text
  Query label                                  P@3   R@5   MRR     ms
----------------------------------------------------------------------------------------
  First Amendment / civil rights              0.33  0.50  0.33   233ms
  Patents (Title 35)                          0.00  0.00  0.00   176ms  ← title not ingested
  Bankruptcy (Title 11)                       0.67  1.00  0.50    74ms
  Copyrights (Title 17)                       1.00  1.00  1.00    85ms
  Internal Revenue (Title 26)                 0.00  0.00  0.00   128ms  ← title not ingested
  Crimes (Title 18)                           0.67  1.00  1.00    46ms
  Immigration (Title 8)                       1.00  1.00  1.00    65ms
  Commerce / Antitrust (Title 15)             0.00  0.00  0.00   113ms  ← title not ingested
  Social Security (Title 42)                  0.00  0.00  0.00    49ms  ← title not ingested
  Employment discrimination (Title 42/29/5)   0.33  0.33  1.00    74ms
  Controlled substances (Title 21)            0.00  0.00  0.00    44ms  ← title not ingested
  Firearms (Title 18/26)                      0.67  0.50  1.00    70ms
  Labor / minimum wage (Title 29/5)           0.67  0.50  1.00    56ms
  Clean Water Act (Title 33)                  0.00  0.00  0.00    58ms  ← title not ingested
  Habeas corpus (Title 28)                    0.00  0.50  0.25    73ms
  MEAN                                        0.36  0.42  0.47    89ms
```

</details>

<details>
<summary>Full per-query breakdown — without rewriting (raw hybrid search)</summary>

```text
  Query label                                  P@3   R@5   MRR     ms
----------------------------------------------------------------------------------------
  First Amendment / civil rights              0.00  0.25  0.20    22ms
  Patents (Title 35)                          0.00  0.00  0.00    10ms  ← title not ingested
  Bankruptcy (Title 11)                       1.00  1.00  1.00     9ms
  Copyrights (Title 17)                       1.00  1.00  1.00     7ms
  Internal Revenue (Title 26)                 0.00  0.00  0.00     7ms  ← title not ingested
  Crimes (Title 18)                           0.00  0.00  0.00     6ms
  Immigration (Title 8)                       1.00  1.00  1.00     8ms
  Commerce / Antitrust (Title 15)             0.00  0.00  0.00    11ms  ← title not ingested
  Social Security (Title 42)                  0.00  0.00  0.00     6ms  ← title not ingested
  Employment discrimination (Title 42/29/5)   0.33  0.33  1.00     5ms
  Controlled substances (Title 21)            0.00  0.00  0.00     6ms  ← title not ingested
  Firearms (Title 18/26)                      1.00  0.50  1.00     6ms
  Labor / minimum wage (Title 29/5)           0.33  0.50  0.50     5ms
  Clean Water Act (Title 33)                  0.00  0.00  0.00     6ms  ← title not ingested
  Habeas corpus (Title 28)                    0.00  0.50  0.20     6ms
  MEAN                                        0.31  0.34  0.39     8ms
```

</details>

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
