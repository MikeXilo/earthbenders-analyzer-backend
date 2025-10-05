# Build stage
FROM ubuntu:22.04 AS builder

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install only the dependencies needed for building
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    build-essential \
    gdal-bin \
    libgdal-dev \
    python3-gdal \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Create and set working directory
WORKDIR /build

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Runtime stage
FROM ubuntu:22.04

# Accept image tag argument (used by docker-compose)
ARG IMAGE_TAG=earthbenders-backend:latest
LABEL image_tag=$IMAGE_TAG

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Set up environment variables
ENV IS_DOCKER=true
ENV CORS_ORIGIN="http://localhost:3000,https://earthbendersmvp.vercel.app,*"
ENV DEBUG=true

# Install only runtime dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    gdal-bin \
    python3-gdal \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

# Create and set working directory
WORKDIR /app

# Copy the installed Python packages from the builder stage
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create data directory and set permissions
RUN mkdir -p /app/data && \
    chmod -R 755 /app

# Expose the port
EXPOSE 8000

# Configure healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["python3", "server.py"] 