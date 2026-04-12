# workers/embedding-worker/state_manager.py
import json
import logging
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any
import redis

logger = logging.getLogger(__name__)


class WorkerState(Enum):
    """Worker lifecycle states"""
    STARTING = "starting"
    LOADING_MODEL = "loading_model"
    IDLE = "idle"
    PROCESSING = "processing"
    ERROR = "error"
    STOPPING = "stopping"
    STOPPED = "stopped"


class WorkerMetrics:
    """Track worker metrics"""
    
    def __init__(self):
        self.total_processed = 0
        self.total_errors = 0
        self.current_batch_size = 0
        self.last_processed_at: Optional[datetime] = None
        self.started_at = datetime.utcnow()
        self.last_error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "total_processed": self.total_processed,
            "total_errors": self.total_errors,
            "current_batch_size": self.current_batch_size,
            "last_processed_at": self.last_processed_at.isoformat() if self.last_processed_at else None,
            "started_at": self.started_at.isoformat(),
            "uptime_seconds": (datetime.utcnow() - self.started_at).total_seconds(),
            "last_error": self.last_error
        }


class StateManager:
    """Manages worker state and publishes to Redis for dashboard"""
    
    def __init__(self, redis_client: redis.Redis, worker_id: str):
        self.redis = redis_client
        self.worker_id = worker_id
        self.current_state = WorkerState.STARTING
        self.metrics = WorkerMetrics()
        
        # Redis keys
        self.state_key = f"worker:embedding:{worker_id}:state"
        self.metrics_key = f"worker:embedding:{worker_id}:metrics"
        self.heartbeat_key = f"worker:embedding:{worker_id}:heartbeat"
        
        self.ttl = 300  # 5 minutes
        
        logger.info(f"StateManager initialized for worker: {worker_id}")
    
    def transition_to(self, new_state: WorkerState, details: Optional[Dict[str, Any]] = None):
        """Transition to a new state and publish"""
        old_state = self.current_state
        self.current_state = new_state
        
        logger.info(f"State transition: {old_state.value} -> {new_state.value}")
        
        self._publish_state(details)
    
    def _publish_state(self, details: Optional[Dict[str, Any]] = None):
        """Publish current state to Redis"""
        state_data = {
            "worker_id": self.worker_id,
            "state": self.current_state.value,
            "timestamp": datetime.utcnow().isoformat(),
            "details": details or {}
        }
        
        try:
            self.redis.setex(
                self.state_key,
                self.ttl,
                json.dumps(state_data)
            )
        except Exception as e:
            logger.error(f"Failed to publish state: {e}")
    
    def publish_metrics(self):
        """Publish current metrics to Redis"""
        try:
            self.redis.setex(
                self.metrics_key,
                self.ttl,
                json.dumps(self.metrics.to_dict())
            )
        except Exception as e:
            logger.error(f"Failed to publish metrics: {e}")
    
    def heartbeat(self):
        """Send heartbeat signal"""
        try:
            self.redis.setex(
                self.heartbeat_key,
                30,  # 30 second TTL
                datetime.utcnow().isoformat()
            )
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")
    
    def record_batch_processed(self, count: int):
        """Record successful batch processing"""
        self.metrics.total_processed += count
        self.metrics.current_batch_size = count
        self.metrics.last_processed_at = datetime.utcnow()
        self.publish_metrics()
    
    def record_error(self, error: str):
        """Record an error"""
        self.metrics.total_errors += 1
        self.metrics.last_error = error
        self.publish_metrics()
    
    def cleanup(self):
        """Clean up Redis keys on shutdown"""
        try:
            self.redis.delete(self.state_key)
            self.redis.delete(self.metrics_key)
            self.redis.delete(self.heartbeat_key)
            logger.info("Cleaned up Redis state")
        except Exception as e:
            logger.error(f"Failed to cleanup Redis: {e}")