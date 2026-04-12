# workers/embedding-worker/embedding_service.py
import logging
import time
from typing import List, Optional
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Handles embedding model loading and generation"""
    
    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model: Optional[SentenceTransformer] = None
        logger.info(f"EmbeddingService created for model: {model_name}")
    
    def load_model(self, max_retries: int = 3, backoff_s: float = 2.0):
        """Load the embedding model with retry logic"""
        if self.model is not None:
            logger.info("Model already loaded")
            return
        
        attempt = 0
        last_exc = None
        
        while attempt < max_retries:
            try:
                logger.info(f"Loading model (attempt {attempt + 1}/{max_retries}): {self.model_name}")
                self.model = SentenceTransformer(self.model_name)
                
                # Try to move to device
                try:
                    self.model.to(self.device)
                    logger.info(f"Model loaded on device: {self.device}")
                except Exception as e:
                    logger.warning(f"Could not move to {self.device}, using CPU: {e}")
                
                logger.info("Model loaded successfully")
                return
                
            except Exception as e:
                last_exc = e
                attempt += 1
                logger.warning(f"Failed to load model (attempt {attempt}): {e}")
                
                if attempt < max_retries:
                    sleep_time = backoff_s * attempt
                    logger.info(f"Retrying in {sleep_time}s...")
                    time.sleep(sleep_time)
        
        logger.error("Failed to load model after all retries", exc_info=last_exc)
        raise RuntimeError(f"Could not load embedding model: {last_exc}")
    
    def generate_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Generate embeddings for a batch of texts"""
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load_model() first")
        
        if not texts:
            return []
        
        logger.debug(f"Generating embeddings for {len(texts)} texts")
        
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True  # Normalize for better cosine similarity
        )
        
        return embeddings.tolist()
    
    def unload_model(self):
        """Unload model to free memory"""
        if self.model is not None:
            del self.model
            self.model = None
            logger.info("Model unloaded")