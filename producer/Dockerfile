FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry==1.8.2

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

# Copy source code
COPY src/ ./src/

# Install the package
RUN poetry install --no-interaction --no-ansi

# Health check endpoint port
EXPOSE 8000

# Run the producer (main.py with NautilusTrader + analytics)
CMD ["python", "-m", "src.main"]
