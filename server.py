"""
Main entry point for the Earthbenders backend application
"""
import os
import sys
import logging
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pathlib import Path
import json
import math
import time
import zipfile
import requests
import numpy as np
from PIL import Image
import base64
import io
import rasterio
from rasterio.transform import from_origin
from rasterio.mask import mask
from shapely.geometry import shape, box
from shapely.ops import unary_union
from rasterio.merge import merge
from whitebox import WhiteboxTools
import geopandas as gpd
# Import our new TileServer
from tile_server import TileServer

# Initialize WhiteboxTools lazily to avoid worker conflicts
wbt = None

def get_whitebox_tools():
    """Get WhiteboxTools instance, initializing lazily to avoid worker conflicts"""
    global wbt
    if wbt is None:
        wbt = WhiteboxTools()
        wbt.verbose = False
    return wbt

# Configure logging first
logging.basicConfig(level=logging.DEBUG, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Set up CORS to allow all origins or use environment variable with fallback
cors_origin = os.environ.get('CORS_ORIGIN', '*')
logger.info(f"Setting CORS origins to: {cors_origin}")

# Parse CORS_ORIGIN - if it contains comma-separated values, split them
# If it contains '*' or is '*', allow all origins
if cors_origin == '*' or '*' in cors_origin:
    cors_origins = '*'
    logger.info("CORS configured to allow all origins (*)")
else:
    # Split comma-separated origins and strip whitespace
    cors_origins = [origin.strip() for origin in cors_origin.split(',') if origin.strip()]
    logger.info(f"CORS configured with specific origins: {cors_origins}")

# Configure CORS with parsed origins
CORS(app, 
     supports_credentials=True, 
     origins=cors_origins,
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     expose_headers=["Content-Type", "Authorization", "Access-Control-Allow-Origin"],
     methods=["GET", "POST", "OPTIONS", "PUT", "DELETE", "PATCH"])

# Set CORS headers for all responses - this is critical for OPTIONS preflight requests
@app.after_request
def after_request(response):
    # Get the origin from the request
    request_origin = request.headers.get('Origin')
    
    # If CORS is set to allow all origins (contains '*')
    if cors_origins == '*':
        response.headers['Access-Control-Allow-Origin'] = '*'
    elif isinstance(cors_origins, list) and request_origin:
        # Check if request origin is in the allowed list
        if request_origin in cors_origins:
            response.headers['Access-Control-Allow-Origin'] = request_origin
    
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, PATCH'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

# NASA Earthdata credentials
EARTHDATA_USERNAME = 'earthbenders'
EARTHDATA_PASSWORD = 'Earthbenders2024!'

# Use absolute path for Windows compatibility
SAVE_DIRECTORY = Path('/app/data')
SAVE_DIRECTORY.mkdir(parents=True, exist_ok=True)

# Log the absolute path for debugging
logger.info(f"Data directory set to: {SAVE_DIRECTORY.absolute()}")

# Set up NASA Earthdata Login connection
class SessionWithHeaderRedirection(requests.Session):
    AUTH_HOST = 'urs.earthdata.nasa.gov'

    def __init__(self, username, password):
        super().__init__()
        self.auth = (username, password)

    def rebuild_auth(self, prepared_request, response):
        headers = prepared_request.headers
        url = prepared_request.url

        if 'Authorization' in headers:
            original_parsed = requests.utils.urlparse(response.request.url)
            redirect_parsed = requests.utils.urlparse(url)

            if (original_parsed.hostname != redirect_parsed.hostname) and \
                    redirect_parsed.hostname != self.AUTH_HOST and \
                    original_parsed.hostname != self.AUTH_HOST:
                del headers['Authorization']

        return

# Create a session
session = SessionWithHeaderRedirection(EARTHDATA_USERNAME, EARTHDATA_PASSWORD)

# Base path for basemaps
BASEMAPS_PATH = os.path.join(os.path.dirname(__file__), 'data', 'basemaps', 'portugal', 'REN2023')

# Initialize the tile server
tile_server = TileServer(app)
logger.info("Vector tile server initialized")

# --- ROUTE REGISTRATION ---
# Import and register all routes from the 'routes' folder.
# This registers: /, /health, /save_polygon, /process_polygon, etc.
try:
    from routes import register_all_routes
    register_all_routes(app)
    logger.info("All modular routes registered.")
except Exception as e:
    logger.error(f"Failed to register routes: {str(e)}")
    # Continue without modular routes - we have direct routes defined above

# --- DEBUG: PRINT ALL REGISTERED ROUTES ---
logger.info("=== FLASK ROUTE MAP ===")
for rule in app.url_map.iter_rules():
    logger.info(f"Route: {rule.rule} | Methods: {rule.methods} | Endpoint: {rule.endpoint}")
logger.info("=== END FLASK ROUTE MAP ===")
# --- END DEBUG ---

# --- BYPASS: DIRECT ROUTE DEFINITIONS ---
# Note: Critical routes are now handled by modular route system

@app.route('/update_analysis_paths/<analysisId>', methods=['PATCH'])
def update_analysis_paths(analysisId):
    """Update analysis record with raster paths"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        logger.info(f"Updating analysis paths for ID: {analysisId}")
        logger.info(f"Raster paths data: {data}")
        
        # For now, just log the update (you can implement database update later)
        return jsonify({
            'status': 'success',
            'message': f'Analysis paths updated for ID: {analysisId}',
            'analysisId': analysisId,
            'updated_paths': data
        })
        
    except Exception as e:
        logger.error(f"Error updating analysis paths: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/db-health', methods=['GET'])
def database_health():
    """Check database connection and create tables if needed"""
    try:
        from services.database import DatabaseService
        db_service = DatabaseService()
        
        if not db_service.enabled:
            return jsonify({
                'status': 'disabled',
                'message': 'Database not configured - DATABASE_URL not set'
            }), 503
        
        # Test connection
        conn = db_service._get_connection()
        if not conn:
            return jsonify({
                'status': 'error',
                'message': 'Database connection failed'
            }), 503
        
        # Check if tables exist
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('polygons', 'analyses', 'file_storage', 'users')
            """)
            existing_tables = [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error checking tables: {str(e)}")
            existing_tables = []
        finally:
            cursor.close()
            conn.close()
        
        return jsonify({
            'status': 'connected',
            'message': 'Database connection successful',
            'tables_exist': existing_tables,
            'tables_expected': ['polygons', 'analyses', 'file_storage', 'users'],
            'all_tables_present': len(existing_tables) == 4
        })
        
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/create-tables', methods=['POST'])
def create_tables_endpoint():
    """Create database tables"""
    try:
        import subprocess
        import os
        
        # Run the create_tables.py script
        result = subprocess.run(['python3', 'create_tables.py'], 
                               capture_output=True, text=True, cwd='/app')
        
        if result.returncode == 0:
            return jsonify({
                'status': 'success',
                'message': 'Tables created successfully',
                'output': result.stdout
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to create tables',
                'error': result.stderr
            }), 500
            
    except Exception as e:
        logger.error(f"Table creation failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
# --- END BYPASS ---

# --- ROOT ROUTE HANDLED BY CORE.PY ---
# The root route is now properly handled by the modular route system

# Add a simple test route to verify Flask is working
@app.route('/test')
def test_route():
    return jsonify({'message': 'Flask app is working!', 'routes': ['/health', '/save_polygon', '/process_polygon']})


# Handle OPTIONS requests for CORS
@app.route('/', methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def options_handler(path=''):
    # Use jsonify_with_cors to ensure CORS headers are included
    from utils.cors import jsonify_with_cors
    return jsonify_with_cors({}), 204  # No content needed for OPTIONS response, status code 204

if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', 8000))
        logger.info(f"Starting Flask server on port {port}")
        logger.info("Backend initialization complete - all routes registered")
        
        # Test that the health endpoint works before starting
        with app.test_client() as client:
            response = client.get('/health')
            if response.status_code == 200:
                logger.info("Health endpoint test passed")
            else:
                logger.warning(f"Health endpoint test failed: {response.status_code}")
        
        app.run(debug=True, host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Failed to start Flask server: {str(e)}")
        raise
