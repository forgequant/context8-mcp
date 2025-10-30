# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies directly
RUN pip install --no-cache-dir \
    "mcp>=1.7.1" \
    "redis>=5.0.0"

# Copy source code
COPY server.py ./

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV REDIS_URL=redis://redis:6379

# Expose port for health checks (optional)
EXPOSE 8080

# Run the MCP server
CMD ["python", "server.py"]
