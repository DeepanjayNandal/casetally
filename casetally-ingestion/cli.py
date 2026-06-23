# ingestion/cli.py
#!/usr/bin/env python3
import argparse
import logging
import os
import sys
from pathlib import Path

from core.db_utils import get_ingestion_session
from plugins.uscode import USCodeIngestor

logger = logging.getLogger(__name__)

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
        session.close()


if __name__ == "__main__":
    main()
