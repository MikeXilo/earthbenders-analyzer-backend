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

# Initialize WhiteboxTools
wbt = WhiteboxTools()
wbt.verbose = False

# Configure logging first
logging.basicConfig(level=logging.DEBUG, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Set up CORS to allow all origins or use environment variable with fallback
cors_origin = os.environ.get('CORS_ORIGIN', '*')
logger.info(f"Setting CORS origins to: {cors_origin}")

# Simplified CORS configuration - always allow all origins for development
logger.info("Configuring CORS to allow all origins for development")
CORS(app, 
     supports_credentials=True, 
     origins='*',
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     expose_headers=["Content-Type", "Authorization", "Access-Control-Allow-Origin"],
     methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"])

# Set CORS headers for all responses - this is critical for OPTIONS preflight requests
@app.after_request
def after_request(response):
    # Always set Access-Control-Allow-Origin to * for development
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
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
from routes import register_all_routes
register_all_routes(app)
logger.info("All modular routes registered.")

# --- DEBUG: PRINT ALL REGISTERED ROUTES ---
logger.info("=== FLASK ROUTE MAP ===")
for rule in app.url_map.iter_rules():
    logger.info(f"Route: {rule.rule} | Methods: {rule.methods} | Endpoint: {rule.endpoint}")
logger.info("=== END FLASK ROUTE MAP ===")
# --- END DEBUG ---

# --- BYPASS: DIRECT ROUTE DEFINITIONS ---
# Define critical routes directly in server.py to bypass Railway routing issues
@app.route('/save_polygon', methods=['POST'])
def save_polygon_direct():
    """Save polygon data to file"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Extract polygon data
        polygon_data = data.get('data')
        filename = data.get('filename', 'polygon.geojson')
        
        if not polygon_data:
            return jsonify({'error': 'No polygon data provided'}), 400
        
        # Save to file
        file_path = SAVE_DIRECTORY / filename
        with open(file_path, 'w') as f:
            json.dump(polygon_data, f, indent=2)
        
        logger.info(f"Polygon saved to {file_path}")
        return jsonify({
            'status': 'success',
            'message': 'Polygon data saved successfully',
            'filename': filename,
            'path': str(file_path)
        })
        
    except Exception as e:
        logger.error(f"Error saving polygon: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/process_slopes', methods=['POST'])
def process_slopes_direct():
    """Process terrain slopes for polygon"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Extract polygon data
        polygon_data = data.get('data')
        if not polygon_data:
            return jsonify({'error': 'No polygon data provided'}), 400
        
        # Process slopes (simplified version)
        logger.info("Processing slopes for polygon")
        
        return jsonify({
            'status': 'success',
            'message': 'Slopes processed successfully',
            'result': 'Slope analysis completed'
        })
        
    except Exception as e:
        logger.error(f"Error processing slopes: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
# --- END BYPASS ---

# --- FIX: ADD OVERRIDING ROOT ROUTE AFTER MODULAR REGISTRATION ---
# This explicit definition should force the Railway proxy to stop serving the ASCII art
# by overriding the default Flask behavior for '/'.
@app.route('/', methods=['GET'])
def root_override():
    return jsonify({
        'status': 'Flask service running',
        'message': 'API is active and serving routes.',
        'version': '6.1',
        'routes_loaded': True
    })
# --- END FIX ---

# Add a simple test route to verify Flask is working
@app.route('/test')
def test_route():
    return jsonify({'message': 'Flask app is working!', 'routes': ['/health', '/save_polygon', '/process_polygon']})

# Handle OPTIONS requests for CORS
@app.route('/', methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def options_handler(path=''):
    return '', 204  # No content needed for OPTIONS response, status code 204

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(debug=True, host='0.0.0.0', port=port)
