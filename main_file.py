# Updated main.py with English comments
"""
Main FastAPI application file
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from contextlib import asynccontextmanager
import asyncio
import json
import logging
from typing import Optional

from database import get_session, init_db, close_db
from models import ProcessingObject, ProcessState, OperationType
from schemas import (
    ProcessingRequest, ProcessingResponse, ProgressResponse,
    StatusResponse, CancelResponse, RetryResponse, DeleteResponse,
    ObjectListResponse, HealthResponse
)
from state_machine import ObjectStateMachine
from queue_manager import QueueManager
from worker import Worker
from config import settings


# Logging setup
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global objects
queue_manager = QueueManager()
workers = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifecycle manager - manage startup and shutdown"""
    # Startup
    logger.info("Application starting up...")
    
    try:
        # Initialize database
        await init_db()
        logger.info("Database initialized")
        
        # Connect to Redis
        await queue_manager.connect()
        logger.info("Connected to Redis")
        
        # Start workers
        for i in range(3):
            worker = Worker(queue_manager)
            workers.append(worker)
            asyncio.create_task(worker.start())
            logger.info(f"Started worker {i + 1}/3")
        
        logger.info(f"Application started successfully with {len(workers)} workers")
        
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Application shutting down...")
    
    try:
        # Stop workers
        for worker in workers:
            await worker.stop()
        logger.info("All workers stopped")
        
        # Disconnect from Redis
        await queue_manager.disconnect()
        logger.info("Disconnected from Redis")
        
        # Close database
        await close_db()
        logger.info("Database connections closed")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    
    logger.info("Application shut down successfully")


# Create application
app = FastAPI(
    title="Object Processing API",
    description="Asynchronous API for object processing with State Machine",
    version="1.0.0",
    lifespan=lifespan
)


@app.post("/api/v1/process", response_model=ProcessingResponse, tags=["Processing"])
async def process_object(
    request: ProcessingRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Create or update object and start processing
    
    - If object with this identifier already exists, existing one will be used
    - Object is placed in queue for processing
    - Processing is executed asynchronously by workers
    """
    logger.info(f"Received processing request for {request.identifier}")
    
    # Find existing object
    result = await session.execute(
        select(ProcessingObject).where(ProcessingObject.identifier == request.identifier)
    )
    obj = result.scalar_one_or_none()
    
    # Create new object if not found
    if not obj:
        obj = ProcessingObject(
            identifier=request.identifier,
            state=ProcessState.PENDING
        )
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        logger.info(f"Created new object with ID {obj.id}")
    else:
        logger.info(f"Found existing object with ID {obj.id}")
    
    # Create state machine
    state_machine = ObjectStateMachine(initial_state=obj.state.value)
    
    # Transition to queue
    if state_machine.can_transition('queue'):
        state_machine.queue()
        obj.state = ProcessState.QUEUED
        await session.commit()
        logger.info(f"Object {obj.id} moved to QUEUED state")
    elif obj.state == ProcessState.QUEUED:
        logger.info(f"Object {obj.id} already in QUEUED state")
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot queue object in state {obj.state.value}"
        )
    
    # Add task to queue
    operations_list = [op.value for op in request.operations] if request.operations else []
    task_id = await queue_manager.enqueue_task({
        "obj_id": str(obj.id),
        "operations": operations_list
    })
    
    logger.info(f"Task {task_id} enqueued for object {obj.id}")
    
    return ProcessingResponse(
        id=str(obj.id),
        identifier=obj.identifier,
        state=obj.state,
        task_id=task_id,
        message="Object queued for processing"
    )


@app.get("/api/v1/progress/{object_id}", response_model=ProgressResponse, tags=["Progress"])
async def get_progress(
    object_id: str,
    session: AsyncSession = Depends(get_session)
):
    """
    Get current object processing progress
    
    Returns detailed information about processing state:
    - Current state
    - Operation execution progress
    - Each operation status
    - Links to artifacts in S3
    - Error information (if any)
    """
    result = await session.execute(
        select(ProcessingObject).where(ProcessingObject.id == object_id)
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
        error_message=obj.error_message,
        created_at=obj.created_at.isoformat() if obj.created_at else None,
        updated_at=obj.updated_at.isoformat() if obj.updated_at else None
    )


@app.get("/api/v1/progress/{object_id}/stream", tags=["Progress"])
async def stream_progress(object_id: str):
    """
    Stream progress updates in real-time via Server-Sent Events (SSE)
    
    Connect to this endpoint to receive real-time updates.
    
    JavaScript usage example:
    ```javascript
    const eventSource = new EventSource('/api/v1/progress/{object_id}/stream');
    eventSource.onmessage = (event) => {
        const progress = JSON.parse(event.data);
        console.log('Progress update:', progress);
    };
    ```
    """
    async def event_stream():
        pubsub = await queue_manager.subscribe_to_progress(object_id)
        
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message['type'] == 'message':
                    data = message['data']
                    yield f"data: {data}\n\n"
                await asyncio.sleep(0.1)
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/api/v1/status", response_model=StatusResponse, tags=["System"])
async def get_status():
    """
    Get processing system status
    
    Returns information about:
    - Task queue size
    - Number of active workers
    - Maximum number of workers
    """
    queue_size = await queue_manager.get_queue_size()
    active_workers = await queue_manager.get_active_workers_count()
    
    return StatusResponse(
        queue_size=queue_size,
        active_workers=active_workers,
        max_workers=queue_manager.max_workers
    )


@app.get("/api/v1/objects/{identifier}", response_model=ProgressResponse, tags=["Objects"])
async def get_object_by_identifier(
    identifier: str,
    session: AsyncSession = Depends(get_session)
):
    """
    Get object by its identifier
    
    Returns complete object information including processing progress
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
        error_message=obj.error_message,
        created_at=obj.created_at.isoformat() if obj.created_at else None,
        updated_at=obj.updated_at.isoformat() if obj.updated_at else None
    )


@app.get("/api/v1/objects", response_model=ObjectListResponse, tags=["Objects"])
async def list_objects(
    state: Optional[ProcessState] = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session)
):
    """
    Get object list with filtering and pagination
    
    Parameters:
    - state: State filter (optional)
    - limit: Maximum number of objects (default 100)
    - offset: Pagination offset (default 0)
    """
    query = select(ProcessingObject)
    
    if state:
        query = query.where(ProcessingObject.state == state)
    
    query = query.limit(limit).offset(offset).order_by(ProcessingObject.created_at.desc())
    
    result = await session.execute(query)
    objects = result.scalars().all()
    
    objects_data = []
    for obj in objects:
        objects_data.append(ProgressResponse(
            id=str(obj.id),
            identifier=obj.identifier,
            state=obj.state.value,
            current_operation=obj.current_operation,
            progress=obj.progress,
            operations_status=obj.operations_status,
            s3_artifacts=obj.s3_artifacts,
            error_message=obj.error_message,
            created_at=obj.created_at.isoformat() if obj.created_at else None,
            updated_at=obj.updated_at.isoformat() if obj.updated_at else None
        ))
    
    return ObjectListResponse(
        objects=objects_data,
        total=len(objects_data),
        limit=limit,
        offset=offset
    )


@app.post("/api/v1/objects/{object_id}/cancel", response_model=CancelResponse, tags=["Control"])
async def cancel_processing(
    object_id: str,
    session: AsyncSession = Depends(get_session)
):
    """
    Cancel object processing (if possible)
    
    Object can be cancelled only if it's in states:
    - PENDING
    - QUEUED
    - PROCESSING
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
        logger.info(f"Object {object_id} cancelled")
        return CancelResponse(
            message="Processing cancelled",
            state=obj.state.value
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel object in state {obj.state.value}"
        )


@app.post("/api/v1/objects/{object_id}/retry", response_model=RetryResponse, tags=["Control"])
async def retry_processing(
    object_id: str,
    session: AsyncSession = Depends(get_session)
):
    """
    Retry object processing after error
    
    Object can be retried only if it's in FAILED state.
    Automatically determines incomplete operations and adds them to queue.
    """
    result = await session.execute(
        select(ProcessingObject).where(ProcessingObject.id == object_id)
    )
    obj = result.scalar_one_or_none()
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    state_machine = ObjectStateMachine(initial_state=obj.state.value)
    
    if state_machine.can_transition('retry'):
        state_machine.retry()
        obj.state = ProcessState.QUEUED
        obj.error_message = None
        await session.commit()
        
        # Determine operations that were not completed
        pending_operations = []
        for op_type in [op.value for op in OperationType]:
            if not obj.operations_status.get(op_type, {}).get("completed"):
                pending_operations.append(op_type)
        
        # Add task back to queue
        task_id = await queue_manager.enqueue_task({
            "obj_id": str(obj.id),
            "operations": pending_operations
        })
        
        logger.info(f"Object {object_id} queued for retry with operations: {pending_operations}")
        
        return RetryResponse(
            message="Object queued for retry",
            state=obj.state.value,
            task_id=task_id
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry object in state {obj.state.value}. Only FAILED objects can be retried."
        )


@app.delete("/api/v1/objects/{object_id}", response_model=DeleteResponse, tags=["Objects"])
async def delete_object(
    object_id: str,
    session: AsyncSession = Depends(get_session)
):
    """
    Delete object from database
    
    Object cannot be deleted if it's in PROCESSING state
    """
    result = await session.execute(
        select(ProcessingObject).where(ProcessingObject.id == object_id)
    )
    obj = result.scalar_one_or_none()
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Check that object is not being processed
    if obj.state == ProcessState.PROCESSING:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete object that is currently being processed. Cancel it first."
        )
    
    await session.delete(obj)
    await session.commit()
    
    logger.info(f"Object {object_id} deleted")
    
    return DeleteResponse(
        message="Object deleted successfully",
        id=object_id
    )


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Service health check
    
    Used for health checks in Kubernetes/Docker
    Checks:
    - Redis availability
    - Number of active workers
    """
    try:
        # Check Redis
        redis_ok = await queue_manager.redis_client.ping()
        
        # Check active workers count
        active_workers = await queue_manager.get_active_workers_count()
        
        return HealthResponse(
            status="healthy",
            redis="ok" if redis_ok else "error",
            active_workers=active_workers,
            max_workers=queue_manager.max_workers
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Service unhealthy: {str(e)}"
        )


@app.get("/", tags=["System"])
async def root():
    """Root endpoint - API information"""
    return {
        "name": "Object Processing API",
        "version": "1.0.0",
        "description": "Asynchronous API for object processing",
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level=settings.LOG_LEVEL.lower()
    )