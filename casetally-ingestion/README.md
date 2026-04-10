# CaseTally Ingestion Service

Ingestion microservice for loading legal source data into the citation-centric database schema.

## Service Summary

- Service name: `casetally-ingestion`
- Runtime: Python CLI workers (batch mode)
- Primary responsibility: Parse source files, chunk content, and upsert into `legal_chunks`/`legal_artifacts`.
- Current implemented source: US Code HTML snapshot ingestion.
- Current maturity: Active for US Code; state-code ingestion remains scaffold-only.

## Responsibilities

This service owns:

- Reading source legal files from archive locations
- Parsing source documents into citation-level records
- Chunking content into deterministic segments
- Upserting `legal_chunks` with version tracking
- Upserting `legal_artifacts` for PDF/HTML metadata
- Marking stale chunks as `is_current = FALSE`
- Recording ingestion run metrics in `ingestion_runs`

This service does not own:

- Embedding generation (delegated to embedding workers)
- Search APIs (backend service)
- Frontend data presentation

## Supported Sources

| Source key | Plugin | Status |
|---|---|---|
| `uscode` | `plugins/uscode.py` | Implemented |
| `state_codes` | `plugins/state_codes.py` | Template only |

## Ingestion Flow

1. CLI initializes DB session and source plugin.
2. Plugin resolves source data directory and discovers files.
3. Parser extracts legal sections and metadata.
4. `BaseIngestor.ingest_document` chunks each section.
5. Chunks are inserted/updated in `legal_chunks`.
6. Artifacts are inserted/updated in `legal_artifacts`.
7. Stale chunks for a citation are deactivated.
8. Run status and counters are persisted in `ingestion_runs`.

## Database Tables Touched

- `legal_chunks`
- `legal_artifacts`
- `ingestion_runs`

Operational behavior:

- Idempotent upsert logic by `clause_id`
- Content change detection by `version_hash`
- Automatic embedding invalidation (`embedding = NULL`) when text changes
- Active/inactive version tracking via `is_current`

## US Code Parsing Behavior

`plugins/uscode.py` currently:

- Finds `*.html` files
- Extracts title numbers from filenames
- Parses sections from `<h3 class="section-head">`
- Builds citations like `<title> U.S.C. � <section>`
- Attempts to map matching title PDF files
- Emits optional PDF page hints from HTML comment markers

If section parsing fails for a file, plugin falls back to a single document citation for that file.

## Directory Resolution (US Code)

US Code files are resolved in this order:

1. `USCODE_DATA_DIR` or `OPENRIGHTS_USCODE_DIR`
2. `--data-dir/uscode`
3. `--data-dir`
4. workspace sibling `casetally-data-archive/uscode`

## CLI Interface

Entrypoint: `cli.py`

```bash
python cli.py --source uscode [--limit N] [--batch-size N] [--data-dir PATH] [--verbose]
```

Flags:

- `--source`: `uscode` or `all`
- `--data-dir`: base directory for source data
- `--limit`: max file count for partial ingestion
- `--batch-size`: commit/progress cadence
- `--verbose`: debug-level logs

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://casetally:casetally@localhost:5432/casetally_law` | DB connection |
| `OPENRIGHTS_DATA_DIR` | `/data` | Default source root |
| `USCODE_DATA_DIR` | unset | Explicit US code directory |
| `OPENRIGHTS_USCODE_DIR` | unset | Alias for US code directory |
| `INGESTION_LOG_PATH` | `/app/logs/ingestion.log` | File log path |

Recommended local override:

```powershell
$env:DATABASE_URL = "postgresql://casetally:strongpassword@localhost:5432/casetally_law"
$env:OPENRIGHTS_DATA_DIR = "..\casetally-data-archive"
$env:USCODE_DATA_DIR = "..\casetally-data-archive\uscode"
$env:INGESTION_LOG_PATH = ".\logs\ingestion.log"
```

## Local Run

```powershell
cd casetally-ingestion
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install sqlalchemy psycopg2-binary beautifulsoup4 requests
python .\cli.py --source uscode --limit 1 --verbose
```

Full ingestion:

```powershell
python .\cli.py --source uscode --batch-size 100
```

## Scheduling Guidance

Typical production setup:

- Trigger ingestion via cron/job runner (daily or weekly)
- Run with explicit source snapshot path
- Store logs and run counters externally
- Alert on `ingestion_runs.status = failed`

## Docker Status

`casetally-ingestion/Dockerfile` is currently empty (`0 bytes`).

This service is currently intended to run directly in Python venv. If containerized execution is required, add a Dockerfile before wiring deployment automation.

## Failure Modes and Recovery

Common failure: DB connection refused.

```powershell
docker network create casetally-network
docker build -t localhost:5000/casetally-db:latest casetally-db
docker compose -f casetally-infrastructure/services/casetally-db/docker-compose.yml up -d
```

Common failure: source path not found.

- Validate `USCODE_DATA_DIR`
- Confirm archive has HTML files
- Run with `--verbose` for resolved path logs

## Code Map

- `cli.py`: CLI entrypoint and source dispatch
- `core/base_ingestor.py`: upsert/versioning/chunk lifecycle
- `core/chunker.py`: text chunking strategy
- `core/db_utils.py`: DB session and engine
- `plugins/uscode.py`: US Code parser and ingestion loop
- `plugins/state_codes.py`: state ingestion scaffolding
- `scrapers/base_scraper.py`: shared scraper base abstractions
