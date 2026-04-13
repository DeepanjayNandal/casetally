# CaseTally Frontend Service

Web client service for CaseTally legal browsing and search experience.

## Service Summary

- Service name: `casetally-frontend`
- Runtime: Next.js 16 + React 19 + TypeScript
- Primary responsibility: render web UI and call backend APIs for search/browse/chat flows.
- Streaming transport target: SSE for web search/chat responses.

## Responsibilities

This service owns:

- Route rendering for legal browsing pages
- UI state management for search and chat
- Client API calls to backend endpoints
- SSE stream handling in browser

This service does not own:

- Search ranking logic
- Embedding generation
- Data ingestion

## Current Route Surface

Notable app routes:

- `/`
- `/chat`
- `/us-code`
- `/state-code`
- `/federal`
- `/political`

## Backend Integration Points

### API Client

- File: `services/api-client.ts`
- Base URL: `NEXT_PUBLIC_API_BASE_URL` (fallback `/api`)

Current client endpoint assumptions include:

- `/us-code`
- `/state-codes`
- `/federal`
- `/politicians`
- `/chat`

These are frontend contract targets and may not yet be fully implemented in backend service.

### SSE Hook

- File: `hooks/use-sse-chat.ts`
- Current stream target: `${backendUrl}/api/chat/stream`
- Expected stream message format:
- text chunks
- optional artifact metadata events

## Tech Stack

- Next.js 16
- React 19
- TypeScript 5
- Tailwind CSS 4
- Radix UI component primitives

## Local Development

Requirements:

- Node.js 20+
- npm

Run:

```bash
cd casetally-frontend
npm install
npm run dev
```

Open:

- `http://localhost:3000`

Build and run production mode:

```bash
npm run build
npm start
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Yes (recommended) | Backend base URL used by `api-client.ts` |
| `NEXTAUTH_URL` | Optional | Auth callback host |
| `NEXT_PUBLIC_SENTRY_DSN` | Optional | Browser telemetry |

Example:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:3001/v1
```

## Docker

Build:

```bash
docker build -t casetally-frontend:latest .
```

Run:

```bash
docker run --rm -p 3000:3000 \
  -e NEXT_PUBLIC_API_BASE_URL=http://host.docker.internal:3001/v1 \
  casetally-frontend:latest
```

Dev compose:

```bash
docker compose up --build
```

## Service Contract Expectations (Web)

For full UX delivery, frontend expects backend to provide:

- Non-streaming search endpoint
- SSE search/chat stream endpoint
- US code browse endpoints
- State code browse endpoints
- Artifact metadata/content endpoints

## Known Gaps

- Some client endpoints currently point to placeholder route shapes.
- SSE hook path may need alignment with final backend path (`/v1/search/stream` or `/v1/chat/stream`).
- API response typing can be tightened once backend OpenAPI contract is stabilized.

## Quality and Operations

Recommended checks:

```bash
npm run lint
npm run build
```

## File Map

- `app/`: routed pages
- `components/`: shared UI and feature components
- `services/api-client.ts`: HTTP client wrapper
- `hooks/use-sse-chat.ts`: SSE client logic
- `styles/`: global styling
- `Dockerfile`: production container build
- `docker-compose.yml`: local dev container run
