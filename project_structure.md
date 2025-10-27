# Структура проекта

```
object-processing-api/
│
├── config.py                 # Конфигурация приложения (Settings)
├── models.py                 # SQLAlchemy модели (ProcessingObject, ProcessState, OperationType)
├── database.py               # Настройка подключения к БД
├── state_machine.py          # State Machine для управления состояниями
├── s3_service.py             # Сервис для работы с S3
├── operations.py             # Операции (Validate, Transform, Enrich, Analyze, Export)
├── processor.py              # Процессор для выполнения операций
├── queue_manager.py          # Менеджер очереди задач (Redis)
├── worker.py                 # Воркер для обработки задач
├── schemas.py                # Pydantic схемы для API
├── main.py                   # Главный файл FastAPI приложения
│
├── requirements.txt          # Python зависимости
├── .env.example              # Пример файла с переменными окружения
├── .env                      # Реальный файл с переменными (создать вручную)
│
├── Dockerfile                # Docker образ для приложения
├── docker-compose.yml        # Docker Compose конфигурация
├── run.sh                    # Скрипт для запуска приложения
│
├── tests/                    # Директория с тестами
│   ├── test_api.py           # Тесты API endpoints
│   ├── test_state_machine.py # Тесты State Machine
│   └── test_operations.py    # Тесты операций
│
└── README.md                 # Документация проекта
```

## Описание файлов

### Основные модули

#### `config.py`
- Класс `Settings` с конфигурацией приложения
- Использует `pydantic-settings` для загрузки из `.env`
- Параметры БД, Redis, S3, воркеров

#### `models.py`
- `ProcessState` - enum состояний объекта
- `OperationType` - enum типов операций
- `ProcessingObject` - модель объекта для обработки
- Метод `to_dict()` для сериализации

#### `database.py`
- Асинхронный engine для PostgreSQL
- Фабрика сессий `async_session_maker`
- `get_session()` - dependency для FastAPI
- `init_db()` - инициализация БД

#### `state_machine.py`
- `ObjectStateMachine` - класс state machine
- Граф переходов между состояниями
- Методы для проверки возможности переходов
- Callbacks для логирования

#### `s3_service.py`
- `S3Service` - сервис для работы с S3
- Методы: upload, download, delete, list артефактов
- Поддержка LocalStack для разработки
- Генерация presigned URLs

#### `operations.py`
- `Operation` - базовый класс операций
- Реализации: Validate, Transform, Enrich, Analyze, Export
- `OperationFactory` - фабрика для создания операций
- Сохранение результатов в S3

#### `processor.py`
- `ObjectProcessor` - процессор для выполнения операций
- Метод `process_object()` - главная логика обработки
- Интеграция со state machine
- Callbacks для обновления прогресса

#### `queue_manager.py`
- `QueueManager` - менеджер очереди на Redis
- FIFO очередь задач
- Управление активными воркерами
- Pub/Sub для real-time обновлений

#### `worker.py`
- `Worker` - воркер для обработки задач
- Бесконечный цикл получения задач
- Ограничение параллелизма (MAX_PARALLEL_WORKERS)
- Graceful shutdown

#### `schemas.py`
- Pydantic модели для API request/response
- Валидация входных данных
- Документация через examples

#### `main.py`
- FastAPI приложение
- 11 endpoints для управления объектами
- Lifecycle management (startup/shutdown)
- Автоматический запуск воркеров

### Конфигурационные файлы

#### `requirements.txt`
Все Python зависимости:
- fastapi, uvicorn - веб фреймворк
- sqlalchemy, asyncpg - БД
- redis - очередь и pub/sub
- boto3 - S3
- transitions - state machine
- pydantic - валидация

#### `.env.example`
Пример переменных окружения для локальной разработки

#### `Dockerfile`
Docker образ на базе Python 3.11-slim

#### `docker-compose.yml`
Полный стек:
- PostgreSQL 15
- Redis 7
- LocalStack (S3)
- API приложение

### Тесты

#### `tests/test_api.py`
- Тесты всех API endpoints
- Использует тестовую БД
- Асинхронные тесты с pytest-asyncio

#### `tests/test_state_machine.py`
- Тесты переходов между состояниями
- Проверка валидации переходов

#### `tests/test_operations.py`
- Тесты фабрики операций
- Тесты выполнения каждой операции

## Зависимости между модулями

```
main.py
  ├── database.py
  ├── models.py
  ├── schemas.py
  ├── queue_manager.py
  └── worker.py
        ├── processor.py
        │     ├── operations.py
        │     │     └── s3_service.py
        │     └── state_machine.py
        └── s3_service.py
```

## Запуск

### Вариант 1: Docker Compose (рекомендуется)
```bash
docker-compose up -d
```

### Вариант 2: Локально
```bash
# 1. Создать .env из .env.example
cp .env.example .env

# 2. Запустить зависимости
docker-compose up -d postgres redis localstack

# 3. Запустить приложение
chmod +x run.sh
./run.sh
```

## API Endpoints

- `POST /api/v1/process` - Отправить объект на обработку
- `GET /api/v1/progress/{object_id}` - Получить прогресс
- `GET /api/v1/progress/{object_id}/stream` - SSE стрим прогресса
- `GET /api/v1/status` - Статус системы
- `GET /api/v1/objects` - Список объектов
- `GET /api/v1/objects/{identifier}` - Получить объект по identifier
- `POST /api/v1/objects/{object_id}/cancel` - Отменить обработку
- `POST /api/v1/objects/{object_id}/retry` - Повторить после ошибки
- `DELETE /api/v1/objects/{object_id}` - Удалить объект
- `GET /health` - Health check
- `GET /` - Информация об API

Документация: `http://localhost:8000/docs`