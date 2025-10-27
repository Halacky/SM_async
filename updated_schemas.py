"""
Pydantic схемы для API (обновлённая версия с флагами пересчёта)
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from models import ProcessState, OperationType
from enum import Enum


class RecalculationMode(str, Enum):
    """Режим пересчёта операций"""
    NONE = "none"  # Использовать существующие артефакты
    REQUESTED_ONLY = "requested_only"  # Пересчитать только запрошенные операции
    WITH_DEPENDENCIES = "with_dependencies"  # Пересчитать запрошенные + все зависимые от них


class ProcessingRequest(BaseModel):
    """Запрос на обработку объекта"""
    
    identifier: str = Field(
        ...,
        description="Идентификатор объекта для обработки",
        example="object-123"
    )
    operations: List[OperationType] = Field(
        default_factory=list,
        description="Список операций для выполнения (пустой список = все операции пропускаются)",
        example=["validate", "transform", "analyze"]
    )
    recalculation_mode: RecalculationMode = Field(
        default=RecalculationMode.NONE,
        description=(
            "Режим пересчёта: "
            "'none' - использовать существующие артефакты, "
            "'requested_only' - пересчитать только запрошенные операции, "
            "'with_dependencies' - пересчитать запрошенные и все зависимые от них"
        )
    )
    force_recalculate: List[OperationType] = Field(
        default_factory=list,
        description="Список операций для принудительного пересчёта (игнорируя существующие артефакты)"
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
    """Ответ на запрос обработки"""
    
    id: str = Field(..., description="UUID объекта в БД")
    identifier: str = Field(..., description="Идентификатор объекта")
    state: ProcessState = Field(..., description="Текущее состояние объекта")
    task_id: Optional[str] = Field(None, description="ID задачи в очереди")
    message: str = Field(..., description="Информационное сообщение")
    planned_operations: List[str] = Field(
        default_factory=list,
        description="Список операций которые будут выполнены (с учетом зависимостей)"
    )
    skipped_operations: List[str] = Field(
        default_factory=list,
        description="Список операций которые будут пропущены (уже выполнены)"
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
    """Информация о прогрессе обработки"""
    
    id: str = Field(..., description="UUID объекта")
    identifier: str = Field(..., description="Идентификатор объекта")
    state: str = Field(..., description="Текущее состояние")
    current_operation: Optional[str] = Field(None, description="Текущая операция")
    progress: Dict[str, Any] = Field(..., description="Детали прогресса")
    operations_status: Dict[str, Any] = Field(..., description="Статус выполнения операций")
    s3_artifacts: Dict[str, Any] = Field(..., description="Ссылки на артефакты в S3")
    error_message: Optional[str] = Field(None, description="Сообщение об ошибке")
    created_at: Optional[str] = Field(None, description="Дата создания")
    updated_at: Optional[str] = Field(None, description="Дата обновления")
    
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
    """Статус системы обработки"""
    
    queue_size: int = Field(..., description="Количество задач в очереди")
    active_workers: int = Field(..., description="Количество активных воркеров")
    max_workers: int = Field(..., description="Максимальное количество воркеров")
    
    class Config:
        json_schema_extra = {
            "example": {
                "queue_size": 5,
                "active_workers": 3,
                "max_workers": 3
            }
        }


class CancelResponse(BaseModel):
    """Ответ на отмену обработки"""
    
    message: str = Field(..., description="Сообщение о результате")
    state: str = Field(..., description="Новое состояние объекта")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "Processing cancelled",
                "state": "cancelled"
            }
        }


class RetryResponse(BaseModel):
    """Ответ на повторную попытку обработки"""
    
    message: str = Field(..., description="Сообщение о результате")
    state: str = Field(..., description="Новое состояние объекта")
    task_id: str = Field(..., description="ID новой задачи")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "Object queued for retry",
                "state": "queued",
                "task_id": "770e8400-e29b-41d4-a716-446655440002"
            }
        }


class DeleteResponse(BaseModel):
    """Ответ на удаление объекта"""
    
    message: str = Field(..., description="Сообщение о результате")
    id: str = Field(..., description="ID удаленного объекта")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "Object deleted successfully",
                "id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }


class ObjectListResponse(BaseModel):
    """Список объектов"""
    
    objects: List[ProgressResponse] = Field(..., description="Список объектов")
    total: int = Field(..., description="Количество объектов в ответе")
    limit: int = Field(..., description="Лимит на запрос")
    offset: int = Field(..., description="Смещение")
    
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
    """Ответ health check"""
    
    status: str = Field(..., description="Общий статус сервиса")
    redis: str = Field(..., description="Статус Redis")
    active_workers: int = Field(..., description="Количество активных воркеров")
    max_workers: int = Field(..., description="Максимальное количество воркеров")
    
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
    """Информация о зависимостях операции"""
    
    operation: str = Field(..., description="Операция")
    dependencies: List[str] = Field(..., description="Прямые зависимости")
    all_dependencies: List[str] = Field(..., description="Все зависимости (транзитивные)")
    dependent_operations: List[str] = Field(..., description="Операции которые зависят от данной")
    
    class Config:
        json_schema_extra = {
            "example": {
                "operation": "transform",
                "dependencies": ["validate"],
                "all_dependencies": ["validate"],
                "dependent_operations": ["enrich"]
            }
        }