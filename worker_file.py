"""
Воркер для обработки задач из очереди
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
    """Воркер для обработки задач из очереди"""
    
    def __init__(self, queue_manager: QueueManager):
        """
        Инициализация воркера
        
        Args:
            queue_manager: Менеджер очереди задач
        """
        self.queue_manager = queue_manager
        self.worker_id = str(uuid.uuid4())
        self.is_running = False
        self.s3_service = S3Service()
        logger.info(f"Worker {self.worker_id} initialized")
    
    async def start(self):
        """Запускает воркер в бесконечном цикле"""
        self.is_running = True
        logger.info(f"Worker {self.worker_id} started and listening for tasks")
        
        while self.is_running:
            try:
                # Проверяем, есть ли свободные слоты для обработки
                active_count = await self.queue_manager.get_active_workers_count()
                
                if active_count >= self.queue_manager.max_workers:
                    # Все слоты заняты, ждем
                    await asyncio.sleep(1)
                    continue
                
                # Пытаемся получить задачу из очереди
                task = await self.queue_manager.dequeue_task()
                
                if task:
                    # Регистрируем себя как активного воркера
                    await self.queue_manager.register_worker(self.worker_id)
                    
                    try:
                        # Обрабатываем задачу
                        await self.process_task(task)
                    finally:
                        # Всегда снимаем регистрацию после завершения
                        await self.queue_manager.unregister_worker(self.worker_id)
                else:
                    # Очередь пуста, небольшая пауза
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"Worker {self.worker_id} encountered error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Пауза при ошибке
    
    async def process_task(self, task: Dict[str, Any]):
        """
        Обрабатывает задачу
        
        Args:
            task: Данные задачи с полями obj_id и operations
        """
        obj_id = task.get("obj_id")
        operations = task.get("operations", [])
        task_id = task.get("task_id")
        
        logger.info(f"Worker {self.worker_id} processing task {task_id} for object {obj_id}")
        logger.info(f"Operations to perform: {operations}")
        
        try:
            # Создаем новую сессию БД для этой задачи
            async with async_session_maker() as session:
                processor = ObjectProcessor(session, self.s3_service)
                
                # Callback для публикации прогресса
                async def progress_callback(progress_data):
                    await self.queue_manager.publish_progress(obj_id, progress_data)
                
                # Запускаем обработку
                await processor.process_object(obj_id, operations, progress_callback)
            
            logger.info(f"Worker {self.worker_id} completed task {task_id} for object {obj_id}")
            
        except Exception as e:
            logger.error(f"Worker {self.worker_id} failed to process task {task_id}: {e}", exc_info=True)
    
    async def stop(self):
        """Останавливает воркер"""
        self.is_running = False
        logger.info(f"Worker {self.worker_id} stopping...")
        
        # Снимаем регистрацию если еще зарегистрированы
        try:
            await self.queue_manager.unregister_worker(self.worker_id)
        except:
            pass
        
        logger.info(f"Worker {self.worker_id} stopped")
    
    def get_id(self) -> str:
        """Возвращает ID воркера"""
        return self.worker_id
    
    def is_active(self) -> bool:
        """Проверяет, активен ли воркер"""
        return self.is_running