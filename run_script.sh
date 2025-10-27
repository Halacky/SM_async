#!/bin/bash

# Скрипт для запуска приложения

echo "Starting Object Processing API..."

# Проверка наличия .env файла
if [ ! -f .env ]; then
    echo "Error: .env file not found!"
    echo "Please create .env file based on .env.example"
    exit 1
fi

# Проверка наличия виртуального окружения
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Активация виртуального окружения
source venv/bin/activate

# Установка зависимостей
echo "Installing dependencies..."
pip install -r requirements.txt

# Запуск приложения
echo "Starting application on http://localhost:8000"
echo "API Documentation: http://localhost:8000/docs"
python main.py