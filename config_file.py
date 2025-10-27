"""
Конфигурация приложения
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost/dbname"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # S3
    S3_BUCKET: str = "my-artifacts-bucket"
    S3_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_ENDPOINT_URL: Optional[str] = None  # Для LocalStack
    
    # Worker settings
    MAX_PARALLEL_WORKERS: int = 3
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()