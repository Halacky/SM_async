# Updated worker.py with English comments
"""
Worker for processing tasks from queue
"""
import asyncio
from queue_manager import QueueManager
from database import async_session_maker
from processor import ObjectProcessor
from s3_service import S3Service
import logging
import uuid
from typing import Dict, Any

logger = logging.getLogger(__name__)

class Worker:
    """Worker for processing tasks from queue"""
    
    def __init__(self, queue_manager: QueueManager):
        """
        Initialize worker
        
        Args:
            queue_manager: Task queue manager
        """
        self.queue_manager = queue_manager
        self.worker_id = str(uuid.uuid4())
        self.is_running = False
        self.s3_service = S3Service()
        logger.info(f"Worker {self.worker_id} initialized")
    
    async def start(self):
        """Start worker in infinite loop"""
        self.is_running = True
        logger.info(f"Worker {self.worker_id} started and listening for tasks")
        
        while self.is_running:
            try:
                # Check if there are free processing slots
                active_count = await self.queue_manager.get_active_workers_count()
                
                if active_count >= self.queue_manager.max_workers:
                    # All slots are busy, wait
                    await asyncio.sleep(1)
                    continue
                
                # Try to get task from queue
                task = await self.queue_manager.dequeue_task()
                
                if task:
                    # Register ourselves as active worker
                    await self.queue_manager.register_worker(self.worker_id)
                    
                    try:
                        # Process task
                        await self.process_task(task)
                    finally:
                        # Always unregister after completion
                        await self.queue_manager.unregister_worker(self.worker_id)
                else:
                    # Queue is empty, short pause
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"Worker {self.worker_id} encountered error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Pause on error
    
    async def process_task(self, task: Dict[str, Any]):
        """
        Process task
        
        Args:
            task: Task data with obj_id and operations fields
        """
        obj_id = task.get("obj_id")
        operations = task.get("operations", [])
        task_id = task.get("task_id")
        
        logger.info(f"Worker {self.worker_id} processing task {task_id} for object {obj_id}")
        logger.info(f"Operations to perform: {operations}")
        
        try:
            # Create new database session for this task
            async with async_session_maker() as session:
                processor = ObjectProcessor(session, self.s3_service)
                
                # Callback for publishing progress
                async def progress_callback(progress_data):
                    await self.queue_manager.publish_progress(obj_id, progress_data)
                
                # Start processing
                await processor.process_object(obj_id, operations, progress_callback)
            
            logger.info(f"Worker {self.worker_id} completed task {task_id} for object {obj_id}")
            
        except Exception as e:
            logger.error(f"Worker {self.worker_id} failed to process task {task_id}: {e}", exc_info=True)
    
    async def stop(self):
        """Stop worker"""
        self.is_running = False
        logger.info(f"Worker {self.worker_id} stopping...")
        
        # Unregister if still registered
        try:
            await self.queue_manager.unregister_worker(self.worker_id)
        except:
            pass
        
        logger.info(f"Worker {self.worker_id} stopped")
    
    def get_id(self) -> str:
        """Get worker ID"""
        return self.worker_id
    
    def is_active(self) -> bool:
        """Check if worker is active"""
        return self.is_running