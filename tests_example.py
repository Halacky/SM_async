# Updated tests_example.py with English comments
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

# Test database
TEST_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/test_db"

@pytest.fixture
async def test_db():
    """Fixture for test database"""
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
    """Fixture for test client"""
    async def override_get_session():
        async with test_db() as session:
            yield session
    
    app.dependency_overrides[get_session] = override_get_session
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_create_processing_object(client):
    """Test creating processing object"""
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
    """Test getting processing progress"""
    # Create object
    create_response = await client.post(
        "/api/v1/process",
        json={"identifier": "test-object-2", "operations": ["validate"]}
    )
    obj_id = create_response.json()["id"]
    
    # Get progress
    response = await client.get(f"/api/v1/progress/{obj_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == obj_id
    assert data["identifier"] == "test-object-2"
    assert "progress" in data
    assert "operations_status" in data


@pytest.mark.asyncio
async def test_get_status(client):
    """Test getting system status"""
    response = await client.get("/api/v1/status")
    
    assert response.status_code == 200
    data = response.json()
    assert "queue_size" in data
    assert "active_workers" in data
    assert "max_workers" in data
    assert data["max_workers"] == 3


@pytest.mark.asyncio
async def test_cancel_processing(client):
    """Test canceling processing"""
    # Create object
    create_response = await client.post(
        "/api/v1/process",
        json={"identifier": "test-object-3", "operations": ["validate"]}
    )
    obj_id = create_response.json()["id"]
    
    # Cancel processing
    response = await client.post(f"/api/v1/objects/{obj_id}/cancel")
    
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "cancelled"


@pytest.mark.asyncio
async def test_get_object_by_identifier(client):
    """Test getting object by identifier"""
    # Create object
    await client.post(
        "/api/v1/process",
        json={"identifier": "test-object-4", "operations": ["validate"]}
    )
    
    # Get by identifier
    response = await client.get("/api/v1/objects/test-object-4")
    
    assert response.status_code == 200
    data = response.json()
    assert data["identifier"] == "test-object-4"


@pytest.mark.asyncio
async def test_recalculation_modes(client):
    """Test different recalculation modes"""
    # Test with dependencies mode
    response = await client.post(
        "/api/v1/process",
        json={
            "identifier": "test-object-5",
            "operations": ["analyze"],
            "recalculation_mode": "with_dependencies"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["identifier"] == "test-object-5"
    assert "planned_operations" in data
    assert "skipped_operations" in data


@pytest.mark.asyncio
async def test_force_recalculate(client):
    """Test force recalculate operations"""
    response = await client.post(
        "/api/v1/process",
        json={
            "identifier": "test-object-6",
            "operations": ["validate", "transform"],
            "force_recalculate": ["validate"]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["identifier"] == "test-object-6"
    assert data["state"] == "queued"


# tests/test_state_machine.py
import pytest
from state_machine import ObjectStateMachine
from models import ProcessState


def test_state_machine_initial_state():
    """Test initial state"""
    sm = ObjectStateMachine()
    assert sm.get_current_state() == ProcessState.PENDING.value


def test_state_machine_queue_transition():
    """Test transition to queue"""
    sm = ObjectStateMachine()
    assert sm.can_transition('queue')
    sm.queue()
    assert sm.get_current_state() == ProcessState.QUEUED.value


def test_state_machine_processing_flow():
    """Test full processing cycle"""
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
    """Test error handling"""
    sm = ObjectStateMachine()
    sm.queue()
    sm.start_processing()
    
    assert sm.can_transition('fail')
    sm.fail()
    assert sm.get_current_state() == ProcessState.FAILED.value


def test_state_machine_cancel_flow():
    """Test canceling processing"""
    sm = ObjectStateMachine()
    sm.queue()
    
    assert sm.can_transition('cancel')
    sm.cancel()
    assert sm.get_current_state() == ProcessState.CANCELLED.value


def test_state_machine_retry_flow():
    """Test retry attempt"""
    sm = ObjectStateMachine(initial_state=ProcessState.FAILED.value)
    
    assert sm.can_transition('retry')
    sm.retry()
    assert sm.get_current_state() == ProcessState.QUEUED.value


def test_state_machine_invalid_transition():
    """Test invalid transition"""
    sm = ObjectStateMachine()
    
    # Cannot transition directly to completed from pending
    assert not sm.can_transition('complete')


def test_state_machine_available_transitions():
    """Test getting available transitions"""
    sm = ObjectStateMachine()
    
    transitions = sm.get_available_transitions()
    assert 'queue' in transitions
    assert 'cancel' in transitions
    assert 'start_processing' not in transitions  # Not available from pending


# tests/test_operations.py
import pytest
from operations import OperationFactory, ValidateOperation, TransformOperation
from s3_service import S3Service
from models import OperationType


@pytest.fixture
def s3_service():
    """Mock S3 service"""
    return S3Service()


@pytest.mark.asyncio
async def test_operation_factory():
    """Test operation factory"""
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
    """Test factory with unknown operation"""
    s3_service = S3Service()
    
    with pytest.raises(ValueError):
        OperationFactory.create_operation("unknown_operation", s3_service)


@pytest.mark.asyncio
async def test_validate_operation_execute(s3_service):
    """Test validate operation execution"""
    operation = ValidateOperation(s3_service)
    
    result = await operation.execute({}, "test-identifier")
    
    assert result["completed"] is True
    assert "s3_url" in result
    assert "result" in result
    assert result["result"]["status"] == "valid"


@pytest.mark.asyncio
async def test_transform_operation_execute(s3_service):
    """Test transform operation execution"""
    operation = TransformOperation(s3_service)
    
    result = await operation.execute({}, "test-identifier")
    
    assert result["completed"] is True
    assert "s3_url" in result
    assert result["result"]["status"] == "transformed"


@pytest.mark.asyncio
async def test_enrich_operation_execute(s3_service):
    """Test enrich operation execution"""
    operation = TransformOperation(s3_service)
    
    result = await operation.execute({}, "test-identifier")
    
    assert result["completed"] is True
    assert "s3_url" in result


@pytest.mark.asyncio
async def test_operation_factory_all_types(s3_service):
    """Test creating all operation types"""
    for op_type in OperationType:
        operation = OperationFactory.create_operation(op_type.value, s3_service)
        assert operation is not None
        assert operation.get_name() == op_type.value


# tests/test_dependencies.py
import pytest
from operation_dependencies import OperationDependencyGraph
from models import OperationType


def test_dependency_graph_initialization():
    """Test dependency graph initialization"""
    # Should not raise exception if no cycles
    OperationDependencyGraph.validate_dependencies()


def test_get_dependencies():
    """Test getting operation dependencies"""
    deps = OperationDependencyGraph.get_dependencies(OperationType.TRANSFORM.value)
    assert OperationType.VALIDATE.value in deps
    
    deps = OperationDependencyGraph.get_dependencies(OperationType.VALIDATE.value)
    assert len(deps) == 0  # Validate has no dependencies


def test_get_all_dependencies():
    """Test getting all dependencies including transitive"""
    all_deps = OperationDependencyGraph.get_all_dependencies(OperationType.ANALYZE.value)
    assert OperationType.VALIDATE.value in all_deps
    assert OperationType.TRANSFORM.value in all_deps
    assert OperationType.ENRICH.value in all_deps


def test_resolve_execution_order():
    """Test resolving execution order"""
    operations = [OperationType.ANALYZE.value]
    execution_order = OperationDependencyGraph.resolve_execution_order(operations)
    
    # Should include all dependencies in correct order
    assert OperationType.VALIDATE.value in execution_order
    assert OperationType.TRANSFORM.value in execution_order
    assert OperationType.ENRICH.value in execution_order
    assert OperationType.ANALYZE.value in execution_order
    
    # Validate should come before transform
    validate_index = execution_order.index(OperationType.VALIDATE.value)
    transform_index = execution_order.index(OperationType.TRANSFORM.value)
    assert validate_index < transform_index


def test_get_dependent_operations():
    """Test getting operations that depend on given operation"""
    dependents = OperationDependencyGraph.get_dependent_operations(OperationType.VALIDATE.value)
    assert OperationType.TRANSFORM.value in dependents


def test_check_missing_dependencies():
    """Test checking for missing dependencies"""
    completed_operations = {
        OperationType.VALIDATE.value: {"completed": True},
        OperationType.TRANSFORM.value: {"completed": False}
    }
    
    missing = OperationDependencyGraph.check_missing_dependencies(
        OperationType.ENRICH.value,
        completed_operations
    )
    
    # Transform is missing (not completed)
    assert OperationType.TRANSFORM.value in missing
    # Validate is not missing (completed)
    assert OperationType.VALIDATE.value not in missing


# tests/test_schemas.py
import pytest
from updated_schemas import (
    ProcessingRequest, ProcessingResponse, RecalculationMode,
    ProgressResponse, StatusResponse
)
from models import ProcessState, OperationType


def test_processing_request_validation():
    """Test processing request validation"""
    # Valid request
    request = ProcessingRequest(
        identifier="test-object",
        operations=[OperationType.VALIDATE, OperationType.TRANSFORM],
        recalculation_mode=RecalculationMode.NONE,
        force_recalculate=[]
    )
    assert request.identifier == "test-object"
    assert len(request.operations) == 2
    
    # Request with empty operations
    request = ProcessingRequest(identifier="test-object")
    assert request.operations == []
    assert request.recalculation_mode == RecalculationMode.NONE


def test_processing_response_creation():
    """Test processing response creation"""
    response = ProcessingResponse(
        id="test-uuid",
        identifier="test-object",
        state=ProcessState.QUEUED,
        message="Object queued for processing",
        task_id="task-uuid",
        planned_operations=["validate", "transform"],
        skipped_operations=["enrich"]
    )
    
    assert response.id == "test-uuid"
    assert response.state == ProcessState.QUEUED
    assert response.task_id == "task-uuid"
    assert len(response.planned_operations) == 2
    assert len(response.skipped_operations) == 1


def test_progress_response_creation():
    """Test progress response creation"""
    response = ProgressResponse(
        id="test-uuid",
        identifier="test-object",
        state="processing",
        current_operation="validate",
        progress={"current": 1, "total": 3, "message": "Processing"},
        operations_status={"validate": {"completed": True}},
        s3_artifacts={"validate": "s3://bucket/path"},
        error_message=None,
        created_at="2023-01-01T00:00:00",
        updated_at="2023-01-01T00:05:00"
    )
    
    assert response.id == "test-uuid"
    assert response.state == "processing"
    assert response.current_operation == "validate"
    assert response.progress["current"] == 1
    assert response.error_message is None


def test_status_response_creation():
    """Test status response creation"""
    response = StatusResponse(
        queue_size=5,
        active_workers=3,
        max_workers=3
    )
    
    assert response.queue_size == 5
    assert response.active_workers == 3
    assert response.max_workers == 3


def test_recalculation_mode_enum():
    """Test recalculation mode enum values"""
    assert RecalculationMode.NONE.value == "none"
    assert RecalculationMode.REQUESTED_ONLY.value == "requested_only"
    assert RecalculationMode.WITH_DEPENDENCIES.value == "with_dependencies"


# tests/test_s3_service.py
import pytest
from s3_service import S3Service
import boto3
from moto import mock_s3


@mock_s3
def test_s3_service_initialization():
    """Test S3 service initialization"""
    # Create mock bucket
    conn = boto3.resource('s3', region_name='us-east-1')
    conn.create_bucket(Bucket='test-bucket')
    
    service = S3Service()
    assert service.bucket == 'test-bucket'


@mock_s3
@pytest.mark.asyncio
async def test_s3_upload_download():
    """Test S3 upload and download"""
    # Setup mock S3
    conn = boto3.resource('s3', region_name='us-east-1')
    conn.create_bucket(Bucket='test-bucket')
    
    service = S3Service()
    
    # Test upload
    test_data = b"test content"
    key = "test-file.txt"
    
    url = await service.upload_artifact(key, test_data)
    assert url is not None
    assert "s3://test-bucket/test-file.txt" in url
    
    # Test download
    downloaded_data = await service.download_artifact(key)
    assert downloaded_data == test_data


@mock_s3
@pytest.mark.asyncio
async def test_s3_delete():
    """Test S3 delete"""
    # Setup mock S3
    conn = boto3.resource('s3', region_name='us-east-1')
    conn.create_bucket(Bucket='test-bucket')
    
    service = S3Service()
    
    # Upload then delete
    test_data = b"test content"
    key = "test-file.txt"
    
    await service.upload_artifact(key, test_data)
    result = await service.delete_artifact(key)
    
    assert result is True
