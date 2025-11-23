# Updated updated_schemas.py with English comments
"""
Pydantic schemas for API (updated version with recalculation flags)
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from models import ProcessState, OperationType
from enum import Enum


class RecalculationMode(str, Enum):
    """Operation recalculation mode"""
    NONE = "none"  # Use existing artifacts
    REQUESTED_ONLY = "requested_only"  # Recalculate only requested operations
    WITH_DEPENDENCIES = "with_dependencies"  # Recalculate requested + all dependent operations


class ProcessingRequest(BaseModel):
    """Object processing request"""
    
    identifier: str = Field(
        ...,
        description="Object identifier for processing",
        example="object-123"
    )
    operations: List[OperationType] = Field(
        default_factory=list,
        description="List of operations to execute (empty list = skip all operations)",
        example=["validate", "transform", "analyze"]
    )
    recalculation_mode: RecalculationMode = Field(
        default=RecalculationMode.NONE,
        description=(
            "Recalculation mode: "
            "'none' - use existing artifacts, "
            "'requested_only' - recalculate only requested operations, "
            "'with_dependencies' - recalculate requested and all dependent operations"
        )
    )
    force_recalculate: List[OperationType] = Field(
        default_factory=list,
        description="List of operations to force recalculate (ignoring existing artifacts)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "identifier": "object-123",
                "operations": ["validate", "transform", "enrich"],
                "recalculation_mode": "none",
                "force_recalculate": []
            }
        }


class ProcessingResponse(BaseModel):
    """Processing request response"""
    
    id: str = Field(..., description="Object UUID in database")
    identifier: str = Field(..., description="Object identifier")
    state: ProcessState = Field(..., description="Current object state")
    task_id: Optional[str] = Field(None, description="Task ID in queue")
    message: str = Field(..., description="Information message")
    planned_operations: List[str] = Field(
        default_factory=list,
        description="List of operations that will be executed (considering dependencies)"
    )
    skipped_operations: List[str] = Field(
        default_factory=list,
        description="List of operations that will be skipped (already executed)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "identifier": "object-123",
                "state": "queued",
                "task_id": "660e8400-e29b-41d4-a716-446655440001",
                "message": "Object queued for processing",
                "planned_operations": ["validate", "transform", "enrich"],
                "skipped_operations": []
            }
        }


class ProgressResponse(BaseModel):
    """Processing progress information"""
    
    id: str = Field(..., description="Object UUID")
    identifier: str = Field(..., description="Object identifier")
    state: str = Field(..., description="Current state")
    current_operation: Optional[str] = Field(None, description="Current operation")
    progress: Dict[str, Any] = Field(..., description="Progress details")
    operations_status: Dict[str, Any] = Field(..., description="Operation execution status")
    s3_artifacts: Dict[str, Any] = Field(..., description="Links to artifacts in S3")
    error_message: Optional[str] = Field(None, description="Error message")
    created_at: Optional[str] = Field(None, description="Creation date")
    updated_at: Optional[str] = Field(None, description="Update date")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "identifier": "object-123",
                "state": "processing",
                "current_operation": "transform",
                "progress": {
                    "current": 2,
                    "total": 3,
                    "message": "Executing transform"
                },
                "operations_status": {
                    "validate": {
                        "completed": True,
                        "s3_url": "s3://bucket/object-123/validate_result.json"
                    }
                },
                "s3_artifacts": {
                    "validate": "s3://bucket/object-123/validate_result.json"
                },
                "error_message": None,
                "created_at": "2025-10-27T10:00:00",
                "updated_at": "2025-10-27T10:05:00"
            }
        }


class StatusResponse(BaseModel):
    """System processing status"""
    
    queue_size: int = Field(..., description="Number of tasks in queue")
    active_workers: int = Field(..., description="Number of active workers")
    max_workers: int = Field(..., description="Maximum number of workers")
    
    class Config:
        json_schema_extra = {
            "example": {
                "queue_size": 5,
                "active_workers": 3,
                "max_workers": 3
            }
        }


class CancelResponse(BaseModel):
    """Cancel processing response"""
    
    message: str = Field(..., description="Result message")
    state: str = Field(..., description="New object state")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "Processing cancelled",
                "state": "cancelled"
            }
        }


class RetryResponse(BaseModel):
    """Retry processing response"""
    
    message: str = Field(..., description="Result message")
    state: str = Field(..., description="New object state")
    task_id: str = Field(..., description="New task ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "Object queued for retry",
                "state": "queued",
                "task_id": "770e8400-e29b-41d4-a716-446655440002"
            }
        }


class DeleteResponse(BaseModel):
    """Delete object response"""
    
    message: str = Field(..., description="Result message")
    id: str = Field(..., description="Deleted object ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "Object deleted successfully",
                "id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }


class ObjectListResponse(BaseModel):
    """Object list"""
    
    objects: List[ProgressResponse] = Field(..., description="List of objects")
    total: int = Field(..., description="Number of objects in response")
    limit: int = Field(..., description="Request limit")
    offset: int = Field(..., description="Offset")
    
    class Config:
        json_schema_extra = {
            "example": {
                "objects": [],
                "total": 0,
                "limit": 100,
                "offset": 0
            }
        }


class HealthResponse(BaseModel):
    """Health check response"""
    
    status: str = Field(..., description="Overall service status")
    redis: str = Field(..., description="Redis status")
    active_workers: int = Field(..., description="Number of active workers")
    max_workers: int = Field(..., description="Maximum number of workers")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "redis": "ok",
                "active_workers": 2,
                "max_workers": 3
            }
        }


class DependencyInfo(BaseModel):
    """Operation dependency information"""
    
    operation: str = Field(..., description="Operation")
    dependencies: List[str] = Field(..., description="Direct dependencies")
    all_dependencies: List[str] = Field(..., description="All dependencies (transitive)")
    dependent_operations: List[str] = Field(..., description="Operations that depend on this operation")
    
    class Config:
        json_schema_extra = {
            "example": {
                "operation": "transform",
                "dependencies": ["validate"],
                "all_dependencies": ["validate"],
                "dependent_operations": ["enrich"]
            }
        }