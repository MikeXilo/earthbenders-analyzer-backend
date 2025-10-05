FROM python:3.9-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application with Gunicorn (Railway will set PORT dynamically)
CMD ["sh", "-c", "echo 'Starting Gunicorn on port ${PORT:-8000}' && gunicorn --bind 0.0.0.0:${PORT:-8000} --timeout 120 --workers 1 --access-logfile - --error-logfile - server:app"]