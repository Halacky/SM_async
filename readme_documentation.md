# Object Processing API

Асинхронное API для обработки объектов с использованием State Machine, очередей задач и мониторингом прогресса в реальном времени.

## Архитектура

### Основные компоненты

1. **FastAPI Application** - REST API для приема запросов
2. **State Machine** - Управление состояниями объектов (библиотека `transitions`)
3. **Queue Manager** - Управление очередью задач через Redis
4. **Worker Pool** - Пул воркеров для параллельной обработки (максимум 3)
5. **Object Processor** - Выполнение операций над объектами
6. **S3 Service** - Хранение артефактов в S3
7. **PostgreSQL** - Хранение состояния объектов

### Диаграмма состояний

```
PENDING → QUEUED → PROCESSING → COMPLETED
            ↓           ↓
        CANCELLED   FAILED
                      ↓
                   QUEUED (retry)
```

### Поддерживаемые операции

- `validate` - Валидация объекта
- `transform` - Трансформация данных
- `enrich` - Обогащение метаданными
- `analyze` - Анализ данных
- `export` - Экспорт результатов

## Быстрый старт

### Требования

- Docker и Docker Compose
- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- AWS S3 (или LocalStack для локальной разработки)

### Установка

1. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd object-processing-api
```

2. Создайте файл `.env`:
```env
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/processing_db
REDIS_URL=redis://redis:6379/0
S3_BUCKET=artifacts-bucket
S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
MAX_PARALLEL_WORKERS=3
```

3. Запустите через Docker Compose:
```bash
docker-compose up -d
```

4. API будет доступно по адресу: `http://localhost:8000`

### Локальная разработка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Запустите PostgreSQL и Redis:
```bash
docker-compose up -d postgres redis localstack
```

3. Примените миграции:
```bash
alembic upgrade head
```

4. Запустите приложение:
```bash
uvicorn main:app --reload
```

## Использование API

### Документация

Swagger UI доступен по адресу: `http://localhost:8000/docs`

### Примеры запросов

#### 1. Отправить объект на обработку

```bash
curl -X POST "http://localhost:8000/api/v1/process" \
  -H "Content-Type: application/json" \
  -d '{
    "identifier": "object-123",
    "operations": ["validate", "transform", "analyze"]
  }'
```

Ответ:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "identifier": "object-123",
  "state": "queued",
  "task_id": "660e8400-e29b-41d4-a716-446655440001",
  "message": "Object queued for processing"
}
```

#### 2. Получить прогресс обработки

```bash
curl "http://localhost:8000/api/v1/progress/550e8400-e29b-41d4-a716-446655440000"
```

Ответ:
```json
{
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
      "completed": true,
      "s3_url": "s3://artifacts-bucket/object-123/validate_result.json"
    },
    "transform": {
      "completed": true,
      "s3_url": "s3://artifacts-bucket/object-123/transform_result.json"
    }
  },
  "s3_artifacts": {
    "validate": "s3://artifacts-bucket/object-123/validate_result.json",
    "transform": "s3://artifacts-bucket/object-123/transform_result.json"
  },
  "error_message": null
}
```

#### 3. Стримить прогресс в реальном времени (SSE)

```bash
curl -N "http://localhost:8000/api/v1/progress/550e8400-e29b-41d4-a716-446655440000/stream"
```

Или через JavaScript:
```javascript
const eventSource = new EventSource(
  'http://localhost:8000/api/v1/progress/550e8400-e29b-41d4-a716-446655440000/stream'
);

eventSource.onmessage = (event) => {
  const progress = JSON.parse(event.data);
  console.log('Progress update:', progress);
};
```

#### 4. Получить статус системы

```bash
curl "http://localhost:8000/api/v1/status"
```

Ответ:
```json
{
  "queue_size": 5,
  "active_workers": 3,
  "max_workers": 3
}
```

#### 5. Получить объект по идентификатору

```bash
curl "http://localhost:8000/api/v1/objects/object-123"
```

#### 6. Отменить обработку

```bash
curl -X POST "http://localhost:8000/api/v1/objects/550e8400-e29b-41d4-a716-446655440000/cancel"
```

## Архитектурные решения

### 1. State Machine

Используется библиотека `transitions` для управления жизненным циклом объектов. Это обеспечивает:
- Четкие правила переходов между состояниями
- Невозможность невалидных переходов
- Легкое расширение новыми состояниями

### 2. Очередь задач

Redis используется для:
- Хранения очереди задач (FIFO)
- Отслеживания активных воркеров
- Pub/Sub для обновлений прогресса в реальном времени

### 3. Ограничение параллелизма

Система ограничивает количество одновременно обрабатываемых объектов до 3:
- Worker проверяет количество активных воркеров перед началом обработки
- Если лимит достигнут, задачи остаются в очереди
- Это предотвращает перегрузку системы

### 4. Идемпотентность операций

Каждая операция проверяет, была ли она уже выполнена:
```python
if obj.operations_status.get(operation_type, {}).get("completed"):
    logger.info(f"Operation {operation_type} already completed, skipping")
    continue
```

### 5. Хранение артефактов

Результаты каждой операции сохраняются в S3:
- Уменьшает нагрузку на БД
- Позволяет хранить большие файлы
- Легко масштабируется

## Масштабирование

### Горизонтальное масштабирование

1. **API серверы** - запустите несколько инстансов FastAPI за load balancer
2. **Workers** - запустите дополнительные worker процессы на разных машинах
3. **PostgreSQL** - используйте master-slave репликацию для чтения
4. **Redis** - используйте Redis Cluster для высокой доступности

### Вертикальное масштабирование

- Увеличьте `MAX_PARALLEL_WORKERS` для обработки большего количества задач
- Добавьте больше ресурсов для БД и Redis
- Используйте connection pooling для БД

## Мониторинг и логирование

### Логи

Все компоненты логируют свою работу:
```python
logger.info(f"Worker {self.worker_id} processing object {obj_id}")
logger.error(f"Error processing object {obj.identifier}: {e}")
```

### Метрики

Рекомендуется добавить:
- Prometheus metrics для мониторинга
- Grafana dashboards для визуализации
- Alerting для критичных событий

Пример добавления метрик:
```python
from prometheus_client import Counter, Histogram

processing_time = Histogram('object_processing_seconds', 'Time spent processing object')
operations_counter = Counter('operations_total', 'Total operations processed', ['operation_type'])
```

## Тестирование

Запуск тестов:
```bash
# Все тесты
pytest

# С покрытием
pytest --cov=. --cov-report=html

# Конкретный тест
pytest tests/test_api.py::test_create_processing_object
```

## Безопасность

### Рекомендации

1. **Аутентификация** - добавьте JWT или API keys
2. **Rate limiting** - используйте `slowapi` для ограничения запросов
3. **Валидация входных данных** - Pydantic уже обеспечивает базовую валидацию
4. **Шифрование** - используйте HTTPS в продакшене
5. **Secrets management** - используйте AWS Secrets Manager или Vault

Пример добавления аутентификации:
```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    # Проверка токена
    pass

@app.post("/api/v1/process", dependencies=[Depends(verify_token)])
async def process_object(...):
    ...
```

## Troubleshooting

### Проблема: Задачи не обрабатываются

Проверьте:
1. Запущены ли workers: `curl http://localhost:8000/api/v1/status`
2. Доступен ли Redis: `redis-cli ping`
3. Логи workers: `docker-compose logs api`

### Проблема: Ошибки подключения к БД

Проверьте:
1. Строку подключения в `.env`
2. Доступна ли БД: `docker-compose ps postgres`
3. Примените миграции: `alembic upgrade head`

### Проблема: Артефакты не загружаются в S3

Проверьте:
1. Настройки AWS credentials
2. Доступность S3 bucket
3. Логи S3 операций

## Roadmap

- [ ] Добавить приоритеты задач
- [ ] Реализовать Dead Letter Queue для failed задач
- [ ] Добавить webhook уведомления при завершении
- [ ] Реализовать batch обработку
- [ ] Добавить GraphQL API
- [ ] Интеграция с Kafka для event streaming
- [ ] UI dashboard для мониторинга

## Лицензия

MIT

## Контакты

Для вопросов и предложений создайте issue в репозитории.