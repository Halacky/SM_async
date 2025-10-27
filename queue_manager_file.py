"""
Менеджер очереди задач
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
    """Менеджер очереди задач на основе Redis"""
    
    def __init__(self):
        """Инициализация менеджера очереди"""
        self.redis_client: Optional[redis.Redis] = None
        self.queue_key = "processing_queue"
        self.active_workers_key = "active_workers"
        self.progress_key_prefix = "progress:"
        self.max_workers = settings.MAX_PARALLEL_WORKERS
        logger.info(f"QueueManager initialized with max_workers={self.max_workers}")
    
    async def connect(self):
        """Подключается к Redis"""
        try:
            self.redis_client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            # Проверяем подключение
            await self.redis_client.ping()
            logger.info("Successfully connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self):
        """Отключается от Redis"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Disconnected from Redis")
    
    async def enqueue_task(self, task_data: Dict[str, Any]) -> str:
        """
        Добавляет задачу в очередь
        
        Args:
            task_data: Данные задачи (должны содержать obj_id и operations)
            
        Returns:
            ID задачи
        """
        task_id = str(uuid.uuid4())
        task_data["task_id"] = task_id
        
        task_json = json.dumps(task_data)
        await self.redis_client.rpush(self.queue_key, task_json)
        
        logger.info(f"Enqueued task {task_id} for object {task_data.get('obj_id')}")
        return task_id
    
    async def dequeue_task(self) -> Optional[Dict[str, Any]]:
        """
        Извлекает задачу из очереди (FIFO)
        
        Returns:
            Данные задачи или None если очередь пуста
        """
        task_json = await self.redis_client.lpop(self.queue_key)
        
        if task_json:
            task_data = json.loads(task_json)
            logger.info(f"Dequeued task {task_data.get('task_id')}")
            return task_data
        
        return None
    
    async def get_queue_size(self) -> int:
        """
        Возвращает размер очереди
        
        Returns:
            Количество задач в очереди
        """
        size = await self.redis_client.llen(self.queue_key)
        return size
    
    async def get_active_workers_count(self) -> int:
        """
        Возвращает количество активных воркеров
        
        Returns:
            Количество активных воркеров
        """
        count = await self.redis_client.scard(self.active_workers_key)
        return count
    
    async def register_worker(self, worker_id: str):
        """
        Регистрирует активного воркера
        
        Args:
            worker_id: ID воркера
        """
        await self.redis_client.sadd(self.active_workers_key, worker_id)
        logger.debug(f"Registered worker {worker_id}")
    
    async def unregister_worker(self, worker_id: str):
        """
        Удаляет воркера из активных
        
        Args:
            worker_id: ID воркера
        """
        await self.redis_client.srem(self.active_workers_key, worker_id)
        logger.debug(f"Unregistered worker {worker_id}")
    
    async def get_active_workers(self) -> set:
        """
        Возвращает список активных воркеров
        
        Returns:
            Множество ID активных воркеров
        """
        workers = await self.redis_client.smembers(self.active_workers_key)
        return workers
    
    async def publish_progress(self, obj_id: str, progress_data: Dict[str, Any]):
        """
        Публикует обновление прогресса
        
        Args:
            obj_id: ID объекта
            progress_data: Данные прогресса
        """
        # Сохраняем последний прогресс с TTL
        progress_key = f"{self.progress_key_prefix}{obj_id}"
        progress_json = json.dumps(progress_data)
        
        await self.redis_client.setex(
            progress_key,
            3600,  # TTL 1 час
            progress_json
        )
        
        # Публикуем в канал для real-time подписчиков
        channel = f"progress:{obj_id}"
        await self.redis_client.publish(channel, progress_json)
        
        logger.debug(f"Published progress update for object {obj_id}")
    
    async def get_progress(self, obj_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает последний сохраненный прогресс
        
        Args:
            obj_id: ID объекта
            
        Returns:
            Данные прогресса или None
        """
        progress_key = f"{self.progress_key_prefix}{obj_id}"
        progress_json = await self.redis_client.get(progress_key)
        
        if progress_json:
            return json.loads(progress_json)
        
        return None
    
    async def subscribe_to_progress(self, obj_id: str):
        """
        Подписывается на обновления прогресса
        
        Args:
            obj_id: ID объекта
            
        Returns:
            PubSub объект для получения сообщений
        """
        pubsub = self.redis_client.pubsub()
        channel = f"progress:{obj_id}"
        await pubsub.subscribe(channel)
        
        logger.debug(f"Subscribed to progress updates for object {obj_id}")
        return pubsub
    
    async def clear_queue(self):
        """Очищает очередь задач (для тестирования)"""
        await self.redis_client.delete(self.queue_key)
        logger.warning("Queue cleared")
    
    async def clear_workers(self):
        """Очищает список активных воркеров (для тестирования)"""
        await self.redis_client.delete(self.active_workers_key)
        logger.warning("Active workers list cleared")