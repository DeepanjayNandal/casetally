# CaseTally

A legal research platform for searching U.S. statutes, codes, and regulations using hybrid search and LLM-powered answers.

## What it does

- Ask any legal question in plain English — query rewriting normalizes it into statutory terminology before search
- Hybrid BM25 + vector search with HNSW indexing across 33,969 U.S. Code chunks
- Answers streamed in real time via SSE, grounded in exact statute citations

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript |
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 |
| Database | PostgreSQL 16 with pgvector extension |
| Search | Hybrid BM25 + vector similarity with HNSW indexing |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| LLM | Groq API (llama-3.1-8b-instant) |
| Cache | Redis |

## Services

```
casetally/
├── casetally-backend/     # FastAPI REST + SSE streaming API
├── casetally-frontend/    # Next.js web app
├── casetally-workers/     # Embedding generation worker
├── casetally-db/          # PostgreSQL schema and migrations
└── casetally-ingestion/   # Legal data ingestion CLI
```

## Local development

### Prerequisites
- Docker and Docker Compose
- Groq API key (free at console.groq.com)

### Setup

```bash
cp .env.local.example .env.local
# Add your GROQ_API_KEY to .env.local

docker compose -f docker-compose.local.yml up
```

Frontend: http://localhost:3000  
Backend: http://localhost:3001  
API docs: http://localhost:3001/docs

### Ingest data

```bash
# Run once to populate the database with US Code
docker compose -f docker-compose.local.yml run --rm ingestion python cli.py --source uscode
```

## Deployment

| Service | Platform |
|---|---|
| Frontend | Vercel |
| Backend | Render |
| Database | Supabase (PostgreSQL + pgvector) |
| Redis | Upstash |
| LLM | Groq (free tier) |

## License

MIT
