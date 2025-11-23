# Updated models.py with English comments and strings
"""
Database models
"""
from sqlalchemy import Column, String, JSON, DateTime, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum


Base = declarative_base()


class ProcessState(str, enum.Enum):
    """Object processing states"""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationType(str, enum.Enum):
    """Object operation types"""
    VALIDATE = "validate"
    TRANSFORM = "transform"
    ENRICH = "enrich"
    ANALYZE = "analyze"
    EXPORT = "export"


class ProcessingObject(Base):
    """Processing object model"""
    
    __tablename__ = "processing_objects"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identifier = Column(String, index=True, nullable=False)
    state = Column(SQLEnum(ProcessState), default=ProcessState.PENDING, nullable=False, index=True)
    
    # Operation execution status
    # Format: {"validate": {"completed": True, "s3_url": "...", "result": {...}}, ...}
    operations_status = Column(JSON, default=dict, nullable=False)
    
    # Links to artifacts in S3
    # Format: {"validate": "s3://bucket/path", "transform": "s3://bucket/path", ...}
    s3_artifacts = Column(JSON, default=dict, nullable=False)
    
    # Current operation
    current_operation = Column(String, nullable=True)
    
    # Execution progress
    # Format: {"current": 2, "total": 5, "message": "Processing..."}
    progress = Column(JSON, default={"current": 0, "total": 0, "message": ""}, nullable=False)
    
    # Error message (if any)
    error_message = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def to_dict(self):
        """Converts model to dictionary"""
        return {
            "id": str(self.id),
            "identifier": self.identifier,
            "state": self.state.value,
            "operations_status": self.operations_status,
            "s3_artifacts": self.s3_artifacts,
            "current_operation": self.current_operation,
            "progress": self.progress,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }