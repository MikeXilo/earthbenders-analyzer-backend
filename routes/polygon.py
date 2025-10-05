"""
Routes for polygon operations (saving, processing)
"""
import logging
from flask import request, jsonify
import json
import os

from services.srtm import get_srtm_data, process_srtm_files
from services.terrain import calculate_centroid
from utils.config import SAVE_DIRECTORY
from utils.file_io import save_geojson

logger = logging.getLogger(__name__)

def register_routes(app):
    """
    Register all polygon-related routes
    
    Args:
        app: Flask application instance
    """
    @app.route('/save_polygon', methods=['POST'])
    def save_polygon():
        try:
            data = request.json
            logger.debug(f"Received data structure: {json.dumps(data, indent=2)}")
            
            if not data or 'data' not in data or 'filename' not in data:
                return jsonify({'error': 'Missing required data'}), 400
            
            geojson_data = data['data']
            filename = data['filename']
            
            # Extract polygon ID if provided
            polygon_id = data.get('id', None)
            
            logger.debug(f"GeoJSON data structure: {json.dumps(geojson_data, indent=2)}")
            logger.info(f"Saving polygon with ID: {polygon_id}")
            
            if not filename.endswith('.geojson'):
                return jsonify({'error': 'Invalid file extension'}), 400
            
            # Save the GeoJSON file into a folder with the ID
            file_path = save_geojson(geojson_data, filename, SAVE_DIRECTORY, polygon_id)
            logger.info(f"Polygon saved to: {file_path}")
            
            # Return success message without processing SRTM
            return jsonify({
                'message': f'Polygon saved successfully as {filename}',
                'file_path': file_path
            }), 200
        except Exception as e:
            logger.exception("Error in save_polygon")
            return jsonify({'error': str(e)}), 500
            
    @app.route('/process_polygon', methods=['POST'])
    def process_polygon():
        try:
            data = request.json
            
            # Check if we have the new format with data and id
            if isinstance(data, dict) and 'data' in data and 'id' in data:
                geojson_data = data['data']
                polygon_id = data['id']
                logger.info(f"Processing polygon with ID: {polygon_id}")
            else:
                # Legacy format where the entire body is the GeoJSON
                geojson_data = data
                polygon_id = None
                logger.warning("Processing polygon without ID - using legacy format")
            
            # Create the polygon session folder path for processed outputs
            if polygon_id:
                polygon_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
                os.makedirs(polygon_folder, exist_ok=True)
                logger.info(f"Using polygon folder for processing outputs: {polygon_folder}")
            else:
                polygon_folder = None
                logger.warning("No polygon ID provided, processed files will be saved in the current directory")
            
            # Get SRTM data - the tiles are stored in SAVE_DIRECTORY/srtm
            # but we pass polygon_folder for any temporary processing files
            logger.info("Getting SRTM data from central SRTM repository")
            srtm_files = get_srtm_data(geojson_data, output_folder=polygon_folder)
            if not srtm_files:
                return jsonify({'error': 'Failed to download SRTM data'}), 400
            
            # Process SRTM data and save processed files in the polygon folder
            logger.info(f"Processing SRTM data, outputs will be saved to: {polygon_folder}")
            srtm_data = process_srtm_files(srtm_files, geojson_data, output_folder=polygon_folder)
            if not srtm_data:
                return jsonify({'error': 'Failed to process SRTM data'}), 500
            
            # If we have a polygon ID, copy the clipped SRTM as the named output file
            if polygon_id and 'clipped_srtm_path' in srtm_data:
                try:
                    # Create specific named SRTM file for this polygon
                    srtm_file_path = os.path.join(polygon_folder, f"{polygon_id}_srtm.tif")
                    
                    # Copy the clipped SRTM to the named file
                    import shutil
                    shutil.copy2(srtm_data['clipped_srtm_path'], srtm_file_path)
                    logger.info(f"Copied clipped SRTM data to: {srtm_file_path}")
                    
                    # Add the file path to the response
                    srtm_data['srtm_file_path'] = srtm_file_path
                except Exception as folder_error:
                    logger.error(f"Error copying SRTM data for polygon {polygon_id}: {str(folder_error)}")
                    # Continue processing even if file copy fails
            
            return jsonify(srtm_data)
        except Exception as e:
            logger.error(f"Error processing polygon: {str(e)}")
            return jsonify({'error': str(e)}), 500
            
    @app.route('/centroid', methods=['POST'])
    def calculate_centroid_route():
        try:
            points = request.json.get('points')
            
            if not points or len(points) < 3:
                return jsonify({'error': 'Not enough points. Need at least 3 for a polygon.'}), 400
            
            centroid = calculate_centroid(points)
            if not centroid:
                return jsonify({'error': 'Failed to calculate centroid'}), 500
                
            return jsonify({'centroid': centroid})
        except Exception as e:
            logger.exception("Error in calculate_centroid")
            return jsonify({'error': str(e)}), 500 