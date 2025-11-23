# Updated queue_manager.py with English comments
"""
Task queue manager
"""
import redis.asyncio as redis
from config import settings
import asyncio
import json
import logging
from typing import Optional, Dict, Any
import uuid


logger = logging.getLogger(__name__)


class QueueManager:
    """Redis-based task queue manager"""
    
    def __init__(self):
        """Initialize queue manager"""
        self.redis_client: Optional[redis.Redis] = None
        self.queue_key = "processing_queue"
        self.active_workers_key = "active_workers"
        self.progress_key_prefix = "progress:"
        self.max_workers = settings.MAX_PARALLEL_WORKERS
        logger.info(f"QueueManager initialized with max_workers={self.max_workers}")
    
    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis_client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            await self.redis_client.ping()
            logger.info("Successfully connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Disconnected from Redis")
    
    async def enqueue_task(self, task_data: Dict[str, Any]) -> str:
        """
        Add task to queue
        
        Args:
            task_data: Task data (must contain obj_id and operations)
            
        Returns:
            Task ID
        """
        task_id = str(uuid.uuid4())
        task_data["task_id"] = task_id
        
        task_json = json.dumps(task_data)
        await self.redis_client.rpush(self.queue_key, task_json)
        
        logger.info(f"Enqueued task {task_id} for object {task_data.get('obj_id')}")
        return task_id
    
    async def dequeue_task(self) -> Optional[Dict[str, Any]]:
        """
        Get task from queue (FIFO)
        
        Returns:
            Task data or None if queue is empty
        """
        task_json = await self.redis_client.lpop(self.queue_key)
        
        if task_json:
            task_data = json.loads(task_json)
            logger.info(f"Dequeued task {task_data.get('task_id')}")
            return task_data
        
        return None
    
    async def get_queue_size(self) -> int:
        """
        Get queue size
        
        Returns:
            Number of tasks in queue
        """
        size = await self.redis_client.llen(self.queue_key)
        return size
    
    async def get_active_workers_count(self) -> int:
        """
        Get active workers count
        
        Returns:
            Number of active workers
        """
        count = await self.redis_client.scard(self.active_workers_key)
        return count
    
    async def register_worker(self, worker_id: str):
        """
        Register active worker
        
        Args:
            worker_id: Worker ID
        """
        await self.redis_client.sadd(self.active_workers_key, worker_id)
        logger.debug(f"Registered worker {worker_id}")
    
    async def unregister_worker(self, worker_id: str):
        """
        Remove worker from active workers
        
        Args:
            worker_id: Worker ID
        """
        await self.redis_client.srem(self.active_workers_key, worker_id)
        logger.debug(f"Unregistered worker {worker_id}")
    
    async def get_active_workers(self) -> set:
        """
        Get list of active workers
        
        Returns:
            Set of active worker IDs
        """
        workers = await self.redis_client.smembers(self.active_workers_key)
        return workers
    
    async def publish_progress(self, obj_id: str, progress_data: Dict[str, Any]):
        """
        Publish progress update
        
        Args:
            obj_id: Object ID
            progress_data: Progress data
        """
        # Save last progress with TTL
        progress_key = f"{self.progress_key_prefix}{obj_id}"
        progress_json = json.dumps(progress_data)
        
        await self.redis_client.setex(
            progress_key,
            3600,  # TTL 1 hour
            progress_json
        )
        
        # Publish to channel for real-time subscribers
        channel = f"progress:{obj_id}"
        await self.redis_client.publish(channel, progress_json)
        
        logger.debug(f"Published progress update for object {obj_id}")
    
    async def get_progress(self, obj_id: str) -> Optional[Dict[str, Any]]:
        """
        Get last saved progress
        
        Args:
            obj_id: Object ID
            
        Returns:
            Progress data or None
        """
        progress_key = f"{self.progress_key_prefix}{obj_id}"
        progress_json = await self.redis_client.get(progress_key)
        
        if progress_json:
            return json.loads(progress_json)
        
        return None
    
    async def subscribe_to_progress(self, obj_id: str):
        """
        Subscribe to progress updates
        
        Args:
            obj_id: Object ID
            
        Returns:
            PubSub object for receiving messages
        """
        pubsub = self.redis_client.pubsub()
        channel = f"progress:{obj_id}"
        await pubsub.subscribe(channel)
        
        logger.debug(f"Subscribed to progress updates for object {obj_id}")
        return pubsub
    
    async def clear_queue(self):
        """Clear task queue (for testing)"""
        await self.redis_client.delete(self.queue_key)
        logger.warning("Queue cleared")
    
    async def clear_workers(self):
        """Clear active workers list (for testing)"""
        await self.redis_client.delete(self.active_workers_key)
        logger.warning("Active workers list cleared")