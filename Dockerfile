# Use Python 3.11 with Ubuntu base for better compatibility
FROM python:3.11-slim

# Set working directory
WORKDIR /workspace

# Install system dependencies for ML libraries
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m -s /bin/bash vscode

# Copy requirements and install Python dependencies
COPY python_agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Set user
USER vscode

# Default command
CMD ["/bin/bash"] 