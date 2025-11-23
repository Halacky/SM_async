#!/bin/bash

echo "Starting Object Processing API..."

if [ ! -f .env ]; then
    echo "Error: .env file not found!"
    echo "Please create .env file based on .env.example"
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Starting application on http://localhost:8000"
echo "API Documentation: http://localhost:8000/docs"
python main.py