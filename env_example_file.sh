# Database Configuration
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/processing_db

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# S3 Configuration
S3_BUCKET=my-artifacts-bucket
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
# AWS_ENDPOINT_URL=http://localhost:4566

# Worker Configuration
MAX_PARALLEL_WORKERS=3

# Logging
LOG_LEVEL=INFO