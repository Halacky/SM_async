# Object Processing System

An asynchronous object processing system with state machine management, built with FastAPI, SQLAlchemy, Redis, and S3-compatible storage.

## Overview

This system provides a robust, scalable solution for processing objects through a series of operations with dependency management, real-time progress tracking, and fault tolerance.

## Key Features

- **State Machine Management**: Comprehensive state transitions for object lifecycle management
- **Operation Dependencies**: Automatic resolution of operation execution order
- **Asynchronous Processing**: Non-blocking architecture with worker pool
- **Real-time Progress**: SSE (Server-Sent Events) for live progress updates
- **S3 Artifact Storage**: Persistent storage of processing results
- **Redis Queue**: Reliable task queue with worker coordination
- **RESTful API**: Clean API endpoints for all operations
- **Health Monitoring**: System status and health checks

## Architecture

```
Client → FastAPI → Redis Queue → Workers → Processing → S3 Storage
                ↓
           PostgreSQL DB
```

## Core Components

### Models (`models_file.py`)
- `ProcessingObject`: Main entity tracking processing state
- `ProcessState`: Enum for object states (PENDING, QUEUED, PROCESSING, etc.)
- `OperationType`: Enum for available operations

### State Machine (`state_machine_file.py`)
- Manages valid state transitions
- Prevents invalid state changes
- Provides transition callbacks

### Operations (`operations_file.py`)
- **Validate**: Object validation and integrity checks
- **Transform**: Data format transformation
- **Enrich**: Metadata enrichment
- **Analyze**: Pattern detection and insights
- **Export**: Result export preparation

### Dependencies (`operation_dependencies.py`)
- Automatic dependency resolution
- Topological sorting for execution order
- Cycle detection and validation

### Queue System (`queue_manager_file.py`)
- Redis-based task queue
- Worker coordination
- Progress publishing
- Real-time updates

## API Endpoints

### Processing
- `POST /api/v1/process` - Create processing request
- `GET /api/v1/progress/{object_id}` - Get progress
- `GET /api/v1/progress/{object_id}/stream` - Stream progress (SSE)

### Objects
- `GET /api/v1/objects/{identifier}` - Get object by identifier
- `GET /api/v1/objects` - List objects with filtering
- `DELETE /api/v1/objects/{object_id}` - Delete object

### Control
- `POST /api/v1/objects/{object_id}/cancel` - Cancel processing
- `POST /api/v1/objects/{object_id}/retry` - Retry failed processing

### System
- `GET /api/v1/status` - System status
- `GET /health` - Health check

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd SM_async
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Configuration**
   Create `.env` file:
   ```env
   DATABASE_URL=postgresql+asyncpg://user:pass@localhost/dbname
   REDIS_URL=redis://localhost:6379/0
   S3_BUCKET=my-artifacts-bucket
   S3_REGION=us-east-1
   AWS_ACCESS_KEY_ID=your_access_key
   AWS_SECRET_ACCESS_KEY=your_secret_key
   MAX_PARALLEL_WORKERS=3
   LOG_LEVEL=INFO
   ```

4. **Database Setup**
   ```bash
   # The system will automatically create tables on first run
   ```

5. **Start the Application**
   ```bash
   python main_file.py
   ```

## Usage Examples

### Start Processing
```bash
curl -X POST "http://localhost:8000/api/v1/process" \
  -H "Content-Type: application/json" \
  -d '{
    "identifier": "my-object-123",
    "operations": ["validate", "transform", "analyze"]
  }'
```

### Monitor Progress
```bash
# Get current progress
curl "http://localhost:8000/api/v1/progress/{object_id}"

# Stream real-time updates
curl "http://localhost:8000/api/v1/progress/{object_id}/stream"
```

### System Status
```bash
curl "http://localhost:8000/api/v1/status"
```

## Operation Dependencies

The system automatically resolves dependencies:
- `transform` requires `validate`
- `enrich` requires `transform` 
- `analyze` requires `enrich`
- `export` requires `analyze`

Requesting `analyze` will automatically include `validate`, `transform`, and `enrich` in the execution plan.

## Worker System

- Multiple workers process tasks concurrently
- Configurable maximum workers (default: 3)
- Automatic task distribution
- Fault tolerance with retry mechanism

## State Transitions

```
PENDING → QUEUED → PROCESSING → COMPLETED
            ↓           ↓
        CANCELLED   FAILED
                      ↓
                   QUEUED (retry)
```

## Testing

Run the comprehensive test suite:
```bash
pytest tests_example.py -v
```

Tests cover:
- API endpoints
- State machine transitions
- Operation execution
- Dependency resolution
- S3 operations

## Configuration

Key configuration options in `config_file.py`:
- Database connection
- Redis settings
- S3 storage
- Worker pool size
- Logging level

## Development

### Adding New Operations
1. Extend `OperationType` enum
2. Create operation class inheriting from `Operation`
3. Register in `OperationFactory`
4. Define dependencies in `OperationDependencyGraph`

### Custom Processing Logic
Override operation `execute()` methods to implement custom business logic while maintaining the state management and progress tracking infrastructure.

## Monitoring

- Built-in health checks
- Real-time queue monitoring
- Worker activity tracking
- Detailed logging

## Production Considerations

- Use PostgreSQL for production database
- Configure Redis persistence
- Set up S3 bucket policies
- Implement proper authentication
- Configure logging and monitoring
- Set up reverse proxy (nginx)
- Use process manager (systemd/supervisor)

