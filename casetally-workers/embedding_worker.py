# workers/embedding-worker/embedding_worker.py
#!/usr/bin/env python3
import os
import logging
import signal
import time
import redis
from typing import List, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from embedding_service import EmbeddingService
from state_manager import StateManager, WorkerState
from shared.models_chunk import LegalChunk

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EmbeddingWorker:
    """
    Worker that processes document chunks and generates embeddings.
    Polls database for chunks without embeddings and processes them in batches.
    """
    
    def __init__(self):
        # Worker configuration
        self.worker_id = os.getenv("HOSTNAME", "embedding-worker-1")
        self.batch_size = int(os.getenv("BATCH_SIZE", "100"))
        self.poll_interval = int(os.getenv("POLL_INTERVAL", "5"))
        self.running = False
        
        # Validate environment
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        # Embedding model configuration
        model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        device = os.getenv("EMBEDDING_DEVICE", "cpu")
        embedding_dim = int(os.getenv("EMBEDDING_DIMENSION", "384"))
        
        logger.info(f"Embedding configuration: model={model_name}, dimension={embedding_dim}, device={device}")
        
        # Database setup with validation
        self.engine = create_engine(
            db_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        
        # Verify database connection on startup
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection verified")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to database: {e}")
        
        # Redis setup
        redis_host = os.getenv("REDIS_HOST", "redis")
        redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=True,
            socket_connect_timeout=5
        )
        
        # Verify Redis connection on startup
        try:
            self.redis_client.ping()
            logger.info("Redis connection verified")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Redis: {e}")
        
        # State management
        self.state_manager = StateManager(self.redis_client, self.worker_id)
        
        # Embedding service
        self.embedding_service = EmbeddingService(model_name, device)
        
        # Signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        
        logger.info(f"Worker {self.worker_id} initialized")
        logger.info(f"Batch size: {self.batch_size}, Poll interval: {self.poll_interval}s")
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.running = False
        self.state_manager.transition_to(
            WorkerState.STOPPING,
            {"reason": f"signal_{signum}"}
        )
    
    def _get_pending_chunks(self, session: Session, limit: int) -> List[Tuple[int, str]]:
        """Fetch chunks that need embeddings using ORM"""
        chunks = session.query(LegalChunk.id, LegalChunk.text_content).filter(
            LegalChunk.embedding.is_(None),
            LegalChunk.is_current.is_(True)
        ).order_by(LegalChunk.id).limit(limit).all()
        return [(chunk.id, chunk.text_content) for chunk in chunks]
    
    def _update_embeddings(
        self,
        session: Session,
        chunk_ids: List[int],
        embeddings: List[List[float]]
    ):
        """Update database with generated embeddings using ORM"""
        for chunk_id, embedding in zip(chunk_ids, embeddings):
            chunk = session.query(LegalChunk).filter(LegalChunk.id == chunk_id).first()
            if chunk:
                chunk.embedding = embedding
    
    def process_batch(self) -> int:
        """Process one batch of chunks - returns number processed"""
        session = self.SessionLocal()
        
        try:
            # Transition to processing state
            self.state_manager.transition_to(WorkerState.PROCESSING)
            
            # Fetch pending chunks
            chunks = self._get_pending_chunks(session, self.batch_size)
            
            if not chunks:
                self.state_manager.transition_to(WorkerState.IDLE)
                return 0
            
            chunk_ids = [chunk[0] for chunk in chunks]
            texts = [chunk[1] for chunk in chunks]
            
            logger.info(f"Processing batch of {len(chunks)} chunks (IDs: {chunk_ids[0]}-{chunk_ids[-1]})")
            
            # Generate embeddings
            embeddings = self.embedding_service.generate_batch(texts)
            
            # Update database
            self._update_embeddings(session, chunk_ids, embeddings)
            session.commit()
            
            # Record success
            self.state_manager.record_batch_processed(len(chunks))
            
            logger.info(f"Successfully processed {len(chunks)} chunks")
            return len(chunks)
            
        except Exception as e:
            logger.error(f"Error processing batch: {e}", exc_info=True)
            session.rollback()
            
            # Record error
            self.state_manager.transition_to(
                WorkerState.ERROR,
                {"error": str(e)}
            )
            self.state_manager.record_error(str(e))
            
            return 0
            
        finally:
            session.close()
    
    def run(self):
        """Main worker loop"""
        try:
            self.running = True
            logger.info("Starting embedding worker...")
            
            # Load embedding model
            self.state_manager.transition_to(WorkerState.LOADING_MODEL)
            self.embedding_service.load_model()
            
            # Ready to process
            self.state_manager.transition_to(WorkerState.IDLE)
            logger.info("Worker ready and waiting for work")
            
            last_heartbeat = time.time()
            
            # Main processing loop
            while self.running:
                # Send heartbeat every 10 seconds
                now = time.time()
                if now - last_heartbeat >= 10:
                    self.state_manager.heartbeat()
                    last_heartbeat = now
                
                # Process a batch
                processed = self.process_batch()
                
                # Sleep if no work available
                if processed == 0:
                    time.sleep(self.poll_interval)
                else:
                    # Transition back to idle after successful processing
                    self.state_manager.transition_to(WorkerState.IDLE)
            
            # Graceful shutdown
            logger.info("Shutting down worker...")
            self.state_manager.transition_to(WorkerState.STOPPED)
            self.embedding_service.unload_model()
            self.state_manager.cleanup()
            
            logger.info("Worker stopped gracefully")
            
        except Exception as e:
            logger.error(f"Fatal error in worker: {e}", exc_info=True)
            self.state_manager.transition_to(
                WorkerState.ERROR,
                {"error": str(e), "fatal": True}
            )
            raise


if __name__ == "__main__":
    worker = EmbeddingWorker()
    worker.run()