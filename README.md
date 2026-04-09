# CaseTally

A legal research platform that lets you search and chat with US federal law using hybrid search and LLM-powered answers.

## What it does

- Search across the entire US Code using a combination of keyword (BM25) and semantic (vector) search
- Ask plain-English questions and get answers grounded in real legal citations
- Responses are streamed in real time via Server-Sent Events

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS |
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.0 |
| Database | PostgreSQL 16 with pgvector extension |
| Search | Hybrid BM25 + vector similarity (pgvector) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| LLM | Groq API (Llama 3) |
| Cache | Redis |

## Services

```
casetally/
├── openrights-backend/     # FastAPI REST + SSE streaming API
├── openrights-frontend/    # Next.js web app
├── openrights-workers/     # Embedding generation worker
├── openrights-db/          # PostgreSQL schema and migrations
└── openrights-ingestion/   # Legal data ingestion CLI
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
