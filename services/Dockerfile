FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY api_server.py .

# Expose port
EXPOSE 8080

# Run the application - single worker to demonstrate pool exhaustion
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8080"]
