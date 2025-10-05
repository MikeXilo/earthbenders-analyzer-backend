"""
Configuration settings for the Earthbenders application
"""
import os
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# NASA Earthdata credentials
EARTHDATA_USERNAME = os.environ.get('EARTHDATA_USERNAME', 'earthbenders')
EARTHDATA_PASSWORD = os.environ.get('EARTHDATA_PASSWORD', 'Earthbenders2024!')

# Determine if running in Docker or local environment
IS_DOCKER = os.environ.get('IS_DOCKER', 'false').lower() == 'true'

# Directory paths
if IS_DOCKER:
    # Docker environment - use absolute Docker paths
    SAVE_DIRECTORY = Path('/app/data')
    logger.info("Running in Docker environment")
else:
    # Local environment - determine based on current dir
    current_dir = Path(__file__).resolve().parent.parent  # backend/ dir
    SAVE_DIRECTORY = current_dir / 'data'
    logger.info("Running in local environment")

# Create necessary directories
SAVE_DIRECTORY.mkdir(parents=True, exist_ok=True)

# Log the absolute path for debugging
logger.info(f"Data directory set to: {SAVE_DIRECTORY.absolute()}")

# Base path for basemaps - derived from execution environment
if IS_DOCKER:
    BASEMAPS_PATH = os.path.join('/app', 'data', 'basemaps', 'portugal', 'REN2023')
else:
    BASEMAPS_PATH = os.path.join(current_dir, 'data', 'basemaps', 'portugal', 'REN2023')

# Ensure basemaps directory exists
Path(BASEMAPS_PATH).mkdir(parents=True, exist_ok=True)
logger.info(f"Basemaps directory set to: {BASEMAPS_PATH}")

# CORS configuration
CORS_ORIGIN = os.environ.get('CORS_ORIGIN', '*')
logger.info(f"CORS origin set to: {CORS_ORIGIN}")

# Server port
PORT = int(os.environ.get('PORT', 8000))
logger.info(f"Server port set to: {PORT}")

# Debug mode
DEBUG = os.environ.get('DEBUG', 'true').lower() == 'true'
logger.info(f"Debug mode: {DEBUG}") 