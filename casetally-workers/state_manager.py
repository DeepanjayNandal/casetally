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

        # Durable per-pod tally of COMMITTED rows.
        #
        # One hash for the whole tier, one field per pod, and deliberately no
        # TTL: every other key here expires or is deleted on shutdown, which is
        # correct for liveness state and useless for accounting. The three keys
        # above all vanish when a pod exits, so once the worker tier began
        # autoscaling, the rows a scaled-away pod had committed became
        # unattributable: a 3,000 row drain could only account for 1,500.
        #
        # A hash rather than a key per pod so a reader gets the whole tier in one
        # HGETALL, and so resetting between demo runs is a single DEL.
        self.committed_key = "worker:embedding:committed"

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
    
    def record_committed(self, count: int):
        """Add `count` to this pod's durable committed tally.

        Call this ONLY after the database commit has returned, so the counter
        can never claim more than is on disk.

        Failures here are swallowed on purpose. This is bookkeeping for a human
        reading a demo, not part of the work: if Redis is unreachable the rows
        are already committed and nothing should be retried, rolled back or
        failed on account of a counter. The worst case is an undercount, which
        is why the row-level checks against the database remain the authority.
        """
        if count <= 0:
            return
        try:
            self.redis.hincrby(self.committed_key, self.worker_id, count)
        except Exception as e:
            logger.warning(
                "Could not record %d committed rows for %s: %s. "
                "The rows are committed; only the tally is short.",
                count, self.worker_id, e,
            )

    def record_error(self, error: str):
        """Record an error"""
        self.metrics.total_errors += 1
        self.metrics.last_error = error
        self.publish_metrics()

    def cleanup(self):
        """Clean up Redis keys on shutdown.

        committed_key is deliberately NOT deleted here. It is the only key that
        has to outlive the pod: deleting it on a graceful exit is exactly how
        the accounting lost track of workers that KEDA scaled away. It is reset
        by demo-worker.sh when a new backlog is created, which is the only
        moment at which the old totals stop being meaningful.
        """
        try:
            self.redis.delete(self.state_key)
            self.redis.delete(self.metrics_key)
            self.redis.delete(self.heartbeat_key)
            logger.info("Cleaned up Redis state")
        except Exception as e:
            logger.error(f"Failed to cleanup Redis: {e}")