FROM python:3.9

WORKDIR /app

# Install system dependencies required by geospatial libraries
# This step fixes the original GDAL dependency issue.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Set up environment variables for GDAL/Rasterio
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
ENV GDAL_DATA=/usr/share/gdal

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
# Note: The requirements.txt must contain 'numpy<2.0.0' to prevent the app crash.
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application with Gunicorn.
# The `sh -c` wrapper is essential for proper variable expansion.
# The echoes are diagnostic to confirm environment variables are set correctly.
CMD ["sh", "-c", "echo \"PORT env var: $PORT\"; echo \"RAILWAY_STATIC_URL: $RAILWAY_STATIC_URL\"; echo \"RAILWAY_PUBLIC_DOMAIN: $RAILWAY_PUBLIC_DOMAIN\"; echo \"Creating database tables...\"; python3 create_tables.py; echo \"Migrating analyses table...\"; python3 migrate_analyses_table.py; echo \"Starting Gunicorn on port $PORT\"; PORT=${PORT:-8000}; exec gunicorn --bind 0.0.0.0:$PORT --timeout 300 --workers 4 --worker-class sync --access-logfile - --error-logfile - server:app"]
