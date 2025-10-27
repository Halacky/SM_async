# requirements.txt
"""
fastapi==0.104.1
uvicorn==0.24.0
sqlalchemy==2.0.23
asyncpg==0.29.0
pydantic==2.5.0
pydantic-settings==2.1.0
transitions==0.9.0
redis==5.0.1
celery==5.3.4
boto3==1.29.7
alembic==1.12.1
"""

# config.py
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost/dbname"
    REDIS_URL: str = "redis://localhost:6379/0"
    S3_BUCKET: str = "my-artifacts-bucket"
    S3_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    MAX_PARALLEL_WORKERS: int = 3
    
    class Config:
        env_file = ".env"

settings = Settings()


# models.py
from sqlalchemy import Column, String, JSON, DateTime, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum

Base = declarative_base()

class ProcessState(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class OperationType(str, enum.Enum):
    VALIDATE = "validate"
    TRANSFORM = "transform"
    ENRICH = "enrich"
    ANALYZE = "analyze"
    EXPORT = "export"

class ProcessingObject(Base):
    __tablename__ = "processing_objects"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identifier = Column(String, index=True, nullable=False)
    state = Column(SQLEnum(ProcessState), default=ProcessState.PENDING, nullable=False)
    operations_status = Column(JSON, default=dict, nullable=False)
    # Format: {"validate": {"completed": True, "s3_url": "..."}, ...}
    s3_artifacts = Column(JSON, default=dict, nullable=False)
    current_operation = Column(String, nullable=True)
    progress = Column(JSON, default={"current": 0, "total": 0, "message": ""})
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "identifier": self.identifier,
            "state": self.state.value,
            "operations_status": self.operations_status,
            "s3_artifacts": self.s3_artifacts,
            "current_operation": self.current_operation,
            "progress": self.progress,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


# database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=True, future=True)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# state_machine.py
from transitions import Machine
from typing import List, Optional
from models import ProcessState, OperationType
import logging

logger = logging.getLogger(__name__)

class ObjectStateMachine:
    """State machine для управления состояниями обработки объекта"""
    
    states = [state.value for state in ProcessState]
    
    transitions_config = [
        {'trigger': 'queue', 'source': ProcessState.PENDING.value, 'dest': ProcessState.QUEUED.value},
        {'trigger': 'start_processing', 'source': ProcessState.QUEUED.value, 'dest': ProcessState.PROCESSING.value},
        {'trigger': 'complete', 'source': ProcessState.PROCESSING.value, 'dest': ProcessState.COMPLETED.value},
        {'trigger': 'fail', 'source': [ProcessState.PROCESSING.value, ProcessState.QUEUED.value], 
         'dest': ProcessState.FAILED.value},
        {'trigger': 'cancel', 'source': [ProcessState.PENDING.value, ProcessState.QUEUED.value, ProcessState.PROCESSING.value],
         'dest': ProcessState.CANCELLED.value},
        {'trigger': 'retry', 'source': ProcessState.FAILED.value, 'dest': ProcessState.QUEUED.value},
    ]
    
    def __init__(self, initial_state: str = ProcessState.PENDING.value):
        self.machine = Machine(
            model=self,
            states=ObjectStateMachine.states,
            transitions=ObjectStateMachine.transitions_config,
            initial=initial_state,
            auto_transitions=False
        )
    
    def get_current_state(self) -> str:
        return self.state
    
    def can_transition(self, trigger: str) -> bool:
        """Проверяет, возможен ли переход"""
        try:
            return self.machine.get_triggers(self.state).__contains__(trigger)
        except:
            return False


# s3_service.py
import boto3
from botocore.exceptions import ClientError
from config import settings
import logging
from typing import Optional
import io

logger = logging.getLogger(__name__)

class S3Service:
    """Сервис для работы с S3"""
    
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        self.bucket = settings.S3_BUCKET
    
    async def upload_artifact(self, key: str, data: bytes) -> Optional[str]:
        """Загружает артефакт в S3"""
        try:
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data
            )
            url = f"s3://{self.bucket}/{key}"
            logger.info(f"Uploaded artifact to {url}")
            return url
        except ClientError as e:
            logger.error(f"Failed to upload artifact: {e}")
            return None
    
    async def download_artifact(self, key: str) -> Optional[bytes]:
        """Скачивает артефакт из S3"""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
            return response['Body'].read()
        except ClientError as e:
            logger.error(f"Failed to download artifact: {e}")
            return None


# operations.py
from abc import ABC, abstractmethod
from typing import Dict, Any
import asyncio
import logging
from s3_service import S3Service
import json

logger = logging.getLogger(__name__)

class Operation(ABC):
    """Базовый класс для операций"""
    
    def __init__(self, s3_service: S3Service):
        self.s3_service = s3_service
    
    @abstractmethod
    async def execute(self, obj_data: Dict[str, Any], identifier: str) -> Dict[str, Any]:
        """Выполняет операцию и возвращает результат"""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Возвращает имя операции"""
        pass


class ValidateOperation(Operation):
    """Операция валидации"""
    
    def get_name(self) -> str:
        return OperationType.VALIDATE.value
    
    async def execute(self, obj_data: Dict[str, Any], identifier: str) -> Dict[str, Any]:
        logger.info(f"Validating object {identifier}")
        await asyncio.sleep(2)  # Имитация работы
        
        result = {"status": "valid", "checks": ["schema", "constraints", "integrity"]}
        artifact_data = json.dumps(result).encode()
        s3_url = await self.s3_service.upload_artifact(
            f"{identifier}/validate_result.json",
            artifact_data
        )
        
        return {"completed": True, "s3_url": s3_url, "result": result}


class TransformOperation(Operation):
    """Операция трансформации"""
    
    def get_name(self) -> str:
        return OperationType.TRANSFORM.value
    
    async def execute(self, obj_data: Dict[str, Any], identifier: str) -> Dict[str, Any]:
        logger.info(f"Transforming object {identifier}")
        await asyncio.sleep(3)
        
        result = {"transformed": True, "format": "v2"}
        artifact_data = json.dumps(result).encode()
        s3_url = await self.s3_service.upload_artifact(
            f"{identifier}/transform_result.json",
            artifact_data
        )
        
        return {"completed": True, "s3_url": s3_url, "result": result}


class EnrichOperation(Operation):
    """Операция обогащения"""
    
    def get_name(self) -> str:
        return OperationType.ENRICH.value
    
    async def execute(self, obj_data: Dict[str, Any], identifier: str) -> Dict[str, Any]:
        logger.info(f"Enriching object {identifier}")
        await asyncio.sleep(2.5)
        
        result = {"enriched_fields": ["metadata", "tags", "relations"]}
        artifact_data = json.dumps(result).encode()
        s3_url = await self.s3_service.upload_artifact(
            f"{identifier}/enrich_result.json",
            artifact_data
        )
        
        return {"completed": True, "s3_url": s3_url, "result": result}


class AnalyzeOperation(Operation):
    """Операция анализа"""
    
    def get_name(self) -> str:
        return OperationType.ANALYZE.value
    
    async def execute(self, obj_data: Dict[str, Any], identifier: str) -> Dict[str, Any]:
        logger.info(f"Analyzing object {identifier}")
        await asyncio.sleep(4)
        
        result = {"insights": ["pattern_detected", "anomaly_score: 0.05"]}
        artifact_data = json.dumps(result).encode()
        s3_url = await self.s3_service.upload_artifact(
            f"{identifier}/analyze_result.json",
            artifact_data
        )
        
        return {"completed": True, "s3_url": s3_url, "result": result}


class ExportOperation(Operation):
    """Операция экспорта"""
    
    def get_name(self) -> str:
        return OperationType.EXPORT.value
    
    async def execute(self, obj_data: Dict[str, Any], identifier: str) -> Dict[str, Any]:
        logger.info(f"Exporting object {identifier}")
        await asyncio.sleep(2)
        
        result = {"export_format": "json", "size": "1.2MB"}
        artifact_data = json.dumps(result).encode()
        s3_url = await self.s3_service.upload_artifact(
            f"{identifier}/export_result.json",
            artifact_data
        )
        
        return {"completed": True, "s3_url": s3_url, "result": result}


class OperationFactory:
    """Фабрика для создания операций"""
    
    @staticmethod
    def create_operation(operation_type: str, s3_service: S3Service) -> Operation:
        operations_map = {
            OperationType.VALIDATE.value: ValidateOperation,
            OperationType.TRANSFORM.value: TransformOperation,
            OperationType.ENRICH.value: EnrichOperation,
            OperationType.ANALYZE.value: AnalyzeOperation,
            OperationType.EXPORT.value: ExportOperation,
        }
        
        operation_class = operations_map.get(operation_type)
        if not operation_class:
            raise ValueError(f"Unknown operation type: {operation_type}")
        
        return operation_class(s3_service)


# processor.py
from typing import List, Optional, Callable
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from models import ProcessingObject, ProcessState
from state_machine import ObjectStateMachine
from operations import OperationFactory
from s3_service import S3Service
import asyncio

logger = logging.getLogger(__name__)

class ObjectProcessor:
    """Процессор для обработки объектов"""
    
    def __init__(self, session: AsyncSession, s3_service: S3Service):
        self.session = session
        self.s3_service = s3_service
        self.operation_factory = OperationFactory()
    
    async def process_object(
        self,
        obj_id: str,
        operations: List[str],
        progress_callback: Optional[Callable] = None
    ):
        """Обрабатывает объект, выполняя указанные операции"""
        
        # Получаем объект из БД
        result = await self.session.execute(
            select(ProcessingObject).where(ProcessingObject.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        
        if not obj:
            logger.error(f"Object {obj_id} not found")
            return
        
        # Создаем state machine
        state_machine = ObjectStateMachine(initial_state=obj.state.value)
        
        try:
            # Переводим в состояние PROCESSING
            if state_machine.can_transition('start_processing'):
                state_machine.start_processing()
                obj.state = ProcessState.PROCESSING
                await self.session.commit()
            
            # Выполняем операции
            total_operations = len(operations)
            for idx, operation_type in enumerate(operations):
                logger.info(f"Processing operation {operation_type} for {obj.identifier}")
                
                # Обновляем прогресс
                obj.current_operation = operation_type
                obj.progress = {
                    "current": idx + 1,
                    "total": total_operations,
                    "message": f"Executing {operation_type}"
                }
                await self.session.commit()
                
                if progress_callback:
                    await progress_callback(obj.to_dict())
                
                # Проверяем, не выполнена ли уже операция
                if obj.operations_status.get(operation_type, {}).get("completed"):
                    logger.info(f"Operation {operation_type} already completed, skipping")
                    continue
                
                # Выполняем операцию
                operation = self.operation_factory.create_operation(operation_type, self.s3_service)
                result = await operation.execute(obj.to_dict(), obj.identifier)
                
                # Сохраняем результат
                operations_status = obj.operations_status or {}
                operations_status[operation_type] = result
                obj.operations_status = operations_status
                
                s3_artifacts = obj.s3_artifacts or {}
                s3_artifacts[operation_type] = result.get("s3_url")
                obj.s3_artifacts = s3_artifacts
                
                await self.session.commit()
            
            # Завершаем обработку
            if state_machine.can_transition('complete'):
                state_machine.complete()
                obj.state = ProcessState.COMPLETED
                obj.current_operation = None
                obj.progress = {
                    "current": total_operations,
                    "total": total_operations,
                    "message": "Completed"
                }
                await self.session.commit()
                
                if progress_callback:
                    await progress_callback(obj.to_dict())
                
                logger.info(f"Successfully processed object {obj.identifier}")
        
        except Exception as e:
            logger.error(f"Error processing object {obj.identifier}: {e}")
            
            if state_machine.can_transition('fail'):
                state_machine.fail()
                obj.state = ProcessState.FAILED
                obj.error_message = str(e)
                await self.session.commit()
                
                if progress_callback:
                    await progress_callback(obj.to_dict())


# queue_manager.py
import redis.asyncio as redis
from config import settings
import asyncio
import json
import logging
from typing import Optional, Dict, Any
import uuid

logger = logging.getLogger(__name__)

class QueueManager:
    """Менеджер очереди задач"""
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.queue_key = "processing_queue"
        self.active_workers_key = "active_workers"
        self.progress_key_prefix = "progress:"
        self.max_workers = settings.MAX_PARALLEL_WORKERS
    
    async def connect(self):
        """Подключается к Redis"""
        self.redis_client = redis.from_url(settings.REDIS_URL)
        logger.info("Connected to Redis")
    
    async def disconnect(self):
        """Отключается от Redis"""
        if self.redis_client:
            await self.redis_client.close()
    
    async def enqueue_task(self, task_data: Dict[str, Any]) -> str:
        """Добавляет задачу в очередь"""
        task_id = str(uuid.uuid4())
        task_data["task_id"] = task_id
        await self.redis_client.rpush(self.queue_key, json.dumps(task_data))
        logger.info(f"Enqueued task {task_id}")
        return task_id
    
    async def dequeue_task(self) -> Optional[Dict[str, Any]]:
        """Извлекает задачу из очереди"""
        task_json = await self.redis_client.lpop(self.queue_key)
        if task_json:
            return json.loads(task_json)
        return None
    
    async def get_active_workers_count(self) -> int:
        """Возвращает количество активных воркеров"""
        return await self.redis_client.scard(self.active_workers_key)
    
    async def register_worker(self, worker_id: str):
        """Регистрирует активного воркера"""
        await self.redis_client.sadd(self.active_workers_key, worker_id)
    
    async def unregister_worker(self, worker_id: str):
        """Удаляет воркера из активных"""
        await self.redis_client.srem(self.active_workers_key, worker_id)
    
    async def publish_progress(self, obj_id: str, progress_data: Dict[str, Any]):
        """Публикует обновление прогресса"""
        await self.redis_client.setex(
            f"{self.progress_key_prefix}{obj_id}",
            3600,  # TTL 1 час
            json.dumps(progress_data)
        )
        await self.redis_client.publish(
            f"progress:{obj_id}",
            json.dumps(progress_data)
        )
    
    async def get_progress(self, obj_id: str) -> Optional[Dict[str, Any]]:
        """Получает текущий прогресс"""
        progress_json = await self.redis_client.get(f"{self.progress_key_prefix}{obj_id}")
        if progress_json:
            return json.loads(progress_json)
        return None
    
    async def subscribe_to_progress(self, obj_id: str):
        """Подписывается на обновления прогресса"""
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(f"progress:{obj_id}")
        return pubsub


# worker.py
import asyncio
from queue_manager import QueueManager
from database import async_session_maker
from processor import ObjectProcessor
from s3_service import S3Service
import logging
import uuid

logger = logging.getLogger(__name__)

class Worker:
    """Воркер для обработки задач из очереди"""
    
    def __init__(self, queue_manager: QueueManager):
        self.queue_manager = queue_manager
        self.worker_id = str(uuid.uuid4())
        self.is_running = False
        self.s3_service = S3Service()
    
    async def start(self):
        """Запускает воркер"""
        self.is_running = True
        logger.info(f"Worker {self.worker_id} started")
        
        while self.is_running:
            # Проверяем, есть ли свободные слоты
            active_count = await self.queue_manager.get_active_workers_count()
            
            if active_count >= self.queue_manager.max_workers:
                await asyncio.sleep(1)
                continue
            
            # Получаем задачу из очереди
            task = await self.queue_manager.dequeue_task()
            
            if task:
                await self.queue_manager.register_worker(self.worker_id)
                
                try:
                    await self.process_task(task)
                finally:
                    await self.queue_manager.unregister_worker(self.worker_id)
            else:
                await asyncio.sleep(1)
    
    async def process_task(self, task: Dict[str, Any]):
        """Обрабатывает задачу"""
        obj_id = task.get("obj_id")
        operations = task.get("operations", [])
        
        logger.info(f"Worker {self.worker_id} processing object {obj_id}")
        
        async with async_session_maker() as session:
            processor = ObjectProcessor(session, self.s3_service)
            
            async def progress_callback(progress_data):
                await self.queue_manager.publish_progress(obj_id, progress_data)
            
            await processor.process_object(obj_id, operations, progress_callback)
        
        logger.info(f"Worker {self.worker_id} completed object {obj_id}")
    
    async def stop(self):
        """Останавливает воркер"""
        self.is_running = False
        logger.info(f"Worker {self.worker_id} stopped")


# schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from models import ProcessState, OperationType

class ProcessingRequest(BaseModel):
    identifier: str = Field(..., description="Идентификатор объекта")
    operations: List[OperationType] = Field(default_factory=list, description="Список операций")

class ProcessingResponse(BaseModel):
    id: str
    identifier: str
    state: ProcessState
    task_id: Optional[str] = None
    message: str

class ProgressResponse(BaseModel):
    id: str
    identifier: str
    state: str
    current_operation: Optional[str]
    progress: Dict[str, Any]
    operations_status: Dict[str, Any]
    s3_artifacts: Dict[str, Any]
    error_message: Optional[str]

class StatusResponse(BaseModel):
    queue_size: int
    active_workers: int
    max_workers: int


# main.py
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from contextlib import asynccontextmanager
import asyncio
import json
import logging

from database import get_session, init_db
from models import ProcessingObject, ProcessState
from schemas import ProcessingRequest, ProcessingResponse, ProgressResponse, StatusResponse
from state_machine import ObjectStateMachine
from queue_manager import QueueManager
from worker import Worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

queue_manager = QueueManager()
workers = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager для FastAPI"""
    # Startup
    await init_db()
    await queue_manager.connect()
    
    # Запускаем воркеры
    for _ in range(3):
        worker = Worker(queue_manager)
        workers.append(worker)
        asyncio.create_task(worker.start())
    
    logger.info("Application started")
    
    yield
    
    # Shutdown
    for worker in workers:
        await worker.stop()
    await queue_manager.disconnect()
    logger.info("Application stopped")

app = FastAPI(title="Object Processing API", lifespan=lifespan)


@app.post("/api/v1/process", response_model=ProcessingResponse)
async def process_object(
    request: ProcessingRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Создает или обновляет объект и запускает обработку
    """
    # Ищем существующий объект
    result = await session.execute(
        select(ProcessingObject).where(ProcessingObject.identifier == request.identifier)
    )
    obj = result.scalar_one_or_none()
    
    # Создаем новый объект если не найден
    if not obj:
        obj = ProcessingObject(
            identifier=request.identifier,
            state=ProcessState.PENDING
        )
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
    
    # Создаем state machine
    state_machine = ObjectStateMachine(initial_state=obj.state.value)
    
    # Переводим в очередь
    if state_machine.can_transition('queue'):
        state_machine.queue()
        obj.state = ProcessState.QUEUED
        await session.commit()
    
    # Добавляем задачу в очередь
    operations_list = [op.value for op in request.operations] if request.operations else []
    task_id = await queue_manager.enqueue_task({
        "obj_id": str(obj.id),
        "operations": operations_list
    })
    
    return ProcessingResponse(
        id=str(obj.id),
        identifier=obj.identifier,
        state=obj.state,
        task_id=task_id,
        message="Object queued for processing"
    )


@app.get("/api/v1/progress/{object_id}", response_model=ProgressResponse)
async def get_progress(
    object_id: str,
    session: AsyncSession = Depends(get_session)
):
    """
    Получает текущий прогресс обработки объекта
    """
    result = await session.execute(
        select(ProcessingObject).where(ProcessingObject.id == object_id)
    )
    obj = result.scalar_one_or_none()
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    state_machine = ObjectStateMachine(initial_state=obj.state.value)
    
    if state_machine.can_transition('cancel'):
        state_machine.cancel()
        obj.state = ProcessState.CANCELLED
        await session.commit()
        return {"message": "Processing cancelled", "state": obj.state.value}
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel from state {obj.state.value}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)code=404, detail="Object not found")
    
    return ProgressResponse(
        id=str(obj.id),
        identifier=obj.identifier,
        state=obj.state.value,
        current_operation=obj.current_operation,
        progress=obj.progress,
        operations_status=obj.operations_status,
        s3_artifacts=obj.s3_artifacts,
        error_message=obj.error_message
    )


@app.get("/api/v1/progress/{object_id}/stream")
async def stream_progress(object_id: str):
    """
    Стримит обновления прогресса в реальном времени (SSE)
    """
    async def event_stream():
        pubsub = await queue_manager.subscribe_to_progress(object_id)
        
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message['type'] == 'message':
                    data = message['data'].decode('utf-8')
                    yield f"data: {data}\n\n"
                await asyncio.sleep(0.1)
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream"
    )


@app.get("/api/v1/status", response_model=StatusResponse)
async def get_status():
    """
    Получает статус системы обработки
    """
    queue_size = await queue_manager.redis_client.llen(queue_manager.queue_key)
    active_workers = await queue_manager.get_active_workers_count()
    
    return StatusResponse(
        queue_size=queue_size,
        active_workers=active_workers,
        max_workers=queue_manager.max_workers
    )


@app.get("/api/v1/objects/{identifier}", response_model=ProgressResponse)
async def get_object_by_identifier(
    identifier: str,
    session: AsyncSession = Depends(get_session)
):
    """
    Получает объект по идентификатору
    """
    result = await session.execute(
        select(ProcessingObject).where(ProcessingObject.identifier == identifier)
    )
    obj = result.scalar_one_or_none()
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    return ProgressResponse(
        id=str(obj.id),
        identifier=obj.identifier,
        state=obj.state.value,
        current_operation=obj.current_operation,
        progress=obj.progress,
        operations_status=obj.operations_status,
        s3_artifacts=obj.s3_artifacts,
        error_message=obj.error_message
    )


@app.post("/api/v1/objects/{object_id}/cancel")
async def cancel_processing(
    object_id: str,
    session: AsyncSession = Depends(get_session)
):
    """
    Отменяет обработку объекта (если возможно)
    """
    result = await session.execute(
        select(ProcessingObject).where(ProcessingObject.id == object_id)
    )
    obj = result.scalar_one_or_none()
    
    if not obj:
        raise HTTPException(status_