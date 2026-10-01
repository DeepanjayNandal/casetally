# ingestion/cli.py
#!/usr/bin/env python3
import argparse
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import text

from core.db_utils import get_ingestion_session
from plugins.uscode import USCodeIngestor

logger = logging.getLogger(__name__)

# Only one ingestion run may touch the corpus at a time.
#
# finalize_deactivation retires every chunk absent from THIS process's
# accumulated _active_clause_ids, so two concurrent runs would each retire the
# chunks the other had just written. A Kubernetes Job with parallelism 1 does
# not prevent that: nothing stops a second `kubectl create job`, or someone
# running cli.py by hand against the same database. Kubernetes config cannot
# make this guarantee, so it lives next to the data instead.
#
# A session-level advisory lock is the right primitive. It is held for exactly
# as long as the connection lives, and Postgres drops it automatically when the
# process dies, so a crashed run leaves nothing behind to clean up. There is no
# lock table, no TTL, and no reaper.
LOCK_NAMESPACE = 1128351557  # 0x43415345, "CASE" in ASCII. Arbitrary but fixed.
LOCK_ID = 1

# Distinct from the generic failure code 1 so the Job's podFailurePolicy can
# match it exactly and refuse to retry: a second run losing the race is a
# correct outcome, not a transient error worth another attempt.
EXIT_ALREADY_RUNNING = 75  # EX_TEMPFAIL from sysexits.h

# Registry of available ingestors
INGESTORS = {
    'uscode': USCodeIngestor,
    # TODO: Add more sources
    # 'ca-codes': CaliforniaCodesIngestor,
    # 'case-law': CaseLawIngestor,
    # 'cfr': CFRIngestor,
}


def configure_logging(verbose: bool = False):
    """Configure logging with a safe file-handler fallback."""
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler()]

    log_path = Path(os.getenv("INGESTION_LOG_PATH", "/app/logs/ingestion.log"))
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path))
    except Exception as e:
        # Continue with console logging when file logging is unavailable.
        print(f"Warning: could not initialize file logging at {log_path}: {e}", file=sys.stderr)

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


def main():
    parser = argparse.ArgumentParser(
        description='CaseTally Legal Document Ingestion Service'
    )
    
    parser.add_argument(
        '--source',
        choices=list(INGESTORS.keys()) + ['all'],
        required=True,
        help='Data source to ingest'
    )
    
    parser.add_argument(
        '--data-dir',
        type=Path,
        default=Path(os.getenv('CASETALLY_DATA_DIR', '/data')),
        help='Data directory path'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of documents to process'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Batch size for processing'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    configure_logging(verbose=args.verbose)
    
    # Get database session
    session = get_ingestion_session()

    # Claim the single-run lock before touching anything. Done before any read
    # or write so a losing run has no side effects at all.
    acquired = session.execute(
        text("SELECT pg_try_advisory_lock(:ns, :id)"),
        {"ns": LOCK_NAMESPACE, "id": LOCK_ID},
    ).scalar()

    if not acquired:
        logger.error(
            "Another ingestion run already holds advisory lock %s/%s. "
            "Exiting %s without reading or writing anything.",
            LOCK_NAMESPACE, LOCK_ID, EXIT_ALREADY_RUNNING,
        )
        session.close()
        sys.exit(EXIT_ALREADY_RUNNING)

    logger.info("Acquired ingestion advisory lock %s/%s", LOCK_NAMESPACE, LOCK_ID)

    try:
        # Determine which sources to run
        sources = INGESTORS.keys() if args.source == 'all' else [args.source]
        
        for source_name in sources:
            logger.info("=" * 60)
            logger.info(f"Starting ingestion: {source_name}")
            logger.info("=" * 60)
            
            # Create ingestor instance
            ingestor_class = INGESTORS[source_name]
            ingestor = ingestor_class(
                session=session,
                data_dir=args.data_dir,
                batch_size=args.batch_size
            )
            
            # Run ingestion
            stats = ingestor.run(limit=args.limit)
            
            logger.info(f"Completed {source_name}")
            logger.info(f"Statistics: {stats}")
        
        logger.info("All ingestion tasks completed successfully")
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        session.rollback()
        sys.exit(1)
        
    finally:
        # Closing the session releases the advisory lock. Doing it explicitly as
        # well makes the release visible rather than implicit, and keeps the
        # intent clear if this function is ever refactored to reuse a session.
        try:
            session.execute(
                text("SELECT pg_advisory_unlock(:ns, :id)"),
                {"ns": LOCK_NAMESPACE, "id": LOCK_ID},
            )
            session.commit()
        except Exception:
            # The connection may already be gone; Postgres releases the lock on
            # disconnect regardless, so this is not worth failing the run over.
            logger.debug("Could not explicitly release the advisory lock", exc_info=True)
        session.close()


if __name__ == "__main__":
    main()
