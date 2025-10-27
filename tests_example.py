# tests/test_api.py
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import asyncio

from main import app
from database import Base, get_session
from models import ProcessingObject, ProcessState, OperationType
from queue_manager import QueueManager

# Тестовая база данных
TEST_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/test_db"

@pytest.fixture
async def test_db():
    """Фикстура для тестовой базы данных"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    yield async_session_maker
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest.fixture
async def client(test_db):
    """Фикстура для тестового клиента"""
    async def override_get_session():
        async with test_db() as session:
            yield session
    
    app.dependency_overrides[get_session] = override_get_session
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_create_processing_object(client):
    """Тест создания объекта для обработки"""
    response = await client.post(
        "/api/v1/process",
        json={
            "identifier": "test-object-1",
            "operations": ["validate", "transform"]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["identifier"] == "test-object-1"
    assert data["state"] == "queued"
    assert "id" in data
    assert "task_id" in data


@pytest.mark.asyncio
async def test_get_progress(client):
    """Тест получения прогресса обработки"""
    # Создаем объект
    create_response = await client.post(
        "/api/v1/process",
        json={"identifier": "test-object-2", "operations": ["validate"]}
    )
    obj_id = create_response.json()["id"]
    
    # Получаем прогресс
    response = await client.get(f"/api/v1/progress/{obj_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == obj_id
    assert data["identifier"] == "test-object-2"
    assert "progress" in data
    assert "operations_status" in data


@pytest.mark.asyncio
async def test_get_status(client):
    """Тест получения статуса системы"""
    response = await client.get("/api/v1/status")
    
    assert response.status_code == 200
    data = response.json()
    assert "queue_size" in data
    assert "active_workers" in data
    assert "max_workers" in data
    assert data["max_workers"] == 3


@pytest.mark.asyncio
async def test_cancel_processing(client):
    """Тест отмены обработки"""
    # Создаем объект
    create_response = await client.post(
        "/api/v1/process",
        json={"identifier": "test-object-3", "operations": ["validate"]}
    )
    obj_id = create_response.json()["id"]
    
    # Отменяем обработку
    response = await client.post(f"/api/v1/objects/{obj_id}/cancel")
    
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "cancelled"


@pytest.mark.asyncio
async def test_get_object_by_identifier(client):
    """Тест получения объекта по идентификатору"""
    # Создаем объект
    await client.post(
        "/api/v1/process",
        json={"identifier": "test-object-4", "operations": ["validate"]}
    )
    
    # Получаем по идентификатору
    response = await client.get("/api/v1/objects/test-object-4")
    
    assert response.status_code == 200
    data = response.json()
    assert data["identifier"] == "test-object-4"


# tests/test_state_machine.py
import pytest
from state_machine import ObjectStateMachine
from models import ProcessState


def test_state_machine_initial_state():
    """Тест начального состояния"""
    sm = ObjectStateMachine()
    assert sm.get_current_state() == ProcessState.PENDING.value


def test_state_machine_queue_transition():
    """Тест перехода в очередь"""
    sm = ObjectStateMachine()
    assert sm.can_transition('queue')
    sm.queue()
    assert sm.get_current_state() == ProcessState.QUEUED.value


def test_state_machine_processing_flow():
    """Тест полного цикла обработки"""
    sm = ObjectStateMachine()
    
    # Pending -> Queued
    sm.queue()
    assert sm.get_current_state() == ProcessState.QUEUED.value
    
    # Queued -> Processing
    sm.start_processing()
    assert sm.get_current_state() == ProcessState.PROCESSING.value
    
    # Processing -> Completed
    sm.complete()
    assert sm.get_current_state() == ProcessState.COMPLETED.value


def test_state_machine_failure_flow():
    """Тест обработки ошибок"""
    sm = ObjectStateMachine()
    sm.queue()
    sm.start_processing()
    
    assert sm.can_transition('fail')
    sm.fail()
    assert sm.get_current_state() == ProcessState.FAILED.value


def test_state_machine_cancel_flow():
    """Тест отмены обработки"""
    sm = ObjectStateMachine()
    sm.queue()
    
    assert sm.can_transition('cancel')
    sm.cancel()
    assert sm.get_current_state() == ProcessState.CANCELLED.value


def test_state_machine_retry_flow():
    """Тест повторной попытки"""
    sm = ObjectStateMachine(initial_state=ProcessState.FAILED.value)
    
    assert sm.can_transition('retry')
    sm.retry()
    assert sm.get_current_state() == ProcessState.QUEUED.value


def test_state_machine_invalid_transition():
    """Тест невалидного перехода"""
    sm = ObjectStateMachine()
    
    # Нельзя перейти сразу в completed из pending
    assert not sm.can_transition('complete')


# tests/test_operations.py
import pytest
from operations import OperationFactory, ValidateOperation, TransformOperation
from s3_service import S3Service
from models import OperationType


@pytest.fixture
def s3_service():
    """Мок S3 сервиса"""
    return S3Service()


@pytest.mark.asyncio
async def test_operation_factory():
    """Тест фабрики операций"""
    s3_service = S3Service()
    
    validate_op = OperationFactory.create_operation(
        OperationType.VALIDATE.value,
        s3_service
    )
    assert isinstance(validate_op, ValidateOperation)
    
    transform_op = OperationFactory.create_operation(
        OperationType.TRANSFORM.value,
        s3_service
    )
    assert isinstance(transform_op, TransformOperation)


@pytest.mark.asyncio
async def test_operation_factory_invalid_type():
    """Тест фабрики с неизвестной операцией"""
    s3_service = S3Service()
    
    with pytest.raises(ValueError):
        OperationFactory.create_operation("unknown_operation", s3_service)


@pytest.mark.asyncio
async def test_validate_operation_execute(s3_service):
    """Тест выполнения операции валидации"""
    operation = ValidateOperation(s3_service)
    
    result = await operation.execute({}, "test-identifier")
    
    assert result["completed"] is True
    assert "s3_url" in result
    assert "result" in result
    assert result["result"]["status"] == "valid"


# pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*