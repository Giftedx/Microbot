#!/bin/bash

# Microbot Development Environment Setup Script

echo "🤖 Setting up Microbot development environment..."

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Build the development container
echo "🐳 Building development container..."
docker build -t microbot-dev .

# Set up Python environment locally (if not using container)
if command -v python3 &> /dev/null; then
    echo "🐍 Setting up Python environment..."
    cd python_agent
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install -r requirements.txt
    cd ..
fi

# Build Java components
if command -v mvn &> /dev/null; then
    echo "☕ Building Java components..."
    mvn clean compile
fi

echo "✅ Development environment setup complete!"
echo ""
echo "To start developing:"
echo "  1. For Python agent: cd python_agent && source venv/bin/activate"
echo "  2. For Java: Use your IDE or mvn commands"
echo "  3. For container development: Use the Cursor dev container features" 