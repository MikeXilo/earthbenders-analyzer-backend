"""
Routes for polygon operations (saving, processing)
"""
import logging
from flask import request, jsonify
import json
import os
import shutil # Added for file copying
from shapely.geometry import shape
from shapely.geometry.polygon import Polygon # Explicitly import Polygon
from datetime import datetime

from services.srtm import get_srtm_data, process_srtm_files
from services.terrain import calculate_centroid
from services.database import DatabaseService  # New import
from utils.config import SAVE_DIRECTORY
from utils.file_io import save_geojson

logger = logging.getLogger(__name__)

# Initialize database service
db_service = DatabaseService()

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
            
            # Extract bounds for database
            try:
                # Extract geometry from Feature object
                if geojson_data.get('type') == 'Feature':
                    geometry_data = geojson_data.get('geometry')
                else:
                    geometry_data = geojson_data
                
                geom = shape(geometry_data)
                min_lon, min_lat, max_lon, max_lat = geom.bounds
                bounds = {
                    'minLon': min_lon,
                    'minLat': min_lat,
                    'maxLon': max_lon,
                    'maxLat': max_lat
                }
            except Exception as e:
                logger.warning(f"Could not extract bounds: {str(e)}")
                bounds = None
            
            # Save metadata to database
            db_result = db_service.save_polygon_metadata(
                polygon_id=polygon_id,
                filename=filename,
                geojson_path=file_path,
                bounds=bounds
            )
            
            # Save file metadata to database
            file_result = db_service.save_file_metadata(
                polygon_id=polygon_id,
                file_name=filename,
                file_path=file_path,
                file_type='geojson'
            )
            
            response = {
                'message': f'Polygon saved successfully as {filename}',
                'file_path': file_path,
                'database_status': db_result,
                'file_metadata_status': file_result
            }
            
            return jsonify(response)
        except Exception as e:
            logger.error(f"Error saving polygon: {str(e)}", exc_info=True)
            return jsonify({'error': str(e)}), 500


    @app.route('/process_polygon', methods=['POST'])
    def process_polygon():
        try:
            data = request.json
            if not data or 'data' not in data:
                return jsonify({'error': 'Missing GeoJSON data'}), 400

            geojson_data = data['data']
            polygon_id = data.get('id', 'default_polygon')
            filename = data.get('filename', 'polygon.geojson')
            
            # Update status to processing
            db_service.update_polygon_status(polygon_id, 'processing')
            
            # --- FIX: Robust GeoJSON Parsing and Boundary Extraction ---
            
            # 1. Convert the GeoJSON dictionary into a Shapely geometry object
            try:
                # Extract geometry from Feature object
                if geojson_data.get('type') == 'Feature':
                    geometry_data = geojson_data.get('geometry')
                else:
                    geometry_data = geojson_data
                
                geom = shape(geometry_data)
                if not isinstance(geom, Polygon):
                     return jsonify({'error': 'GeoJSON data is not a valid Polygon feature.'}), 400
            except Exception as e:
                logger.error(f"Failed to parse GeoJSON into Shapely geometry: {str(e)}", exc_info=True)
                return jsonify({'error': f'Invalid GeoJSON structure: {str(e)}'}), 400

            # 2. Get the bounding box (bbox) from the Shapely object (minx, miny, maxx, maxy)
            # This handles all coordinate structures internally and avoids the 'string index out of range' error.
            min_lon, min_lat, max_lon, max_lat = geom.bounds
            
            # -----------------------------------------------------------

            # 3. Fetch SRTM data based on the GeoJSON polygon
            logger.info(f"Fetching SRTM data for polygon bounds: {min_lon}, {min_lat}, {max_lon}, {max_lat}")
            srtm_files = get_srtm_data(geojson_data)
            
            if not srtm_files:
                db_service.update_polygon_status(polygon_id, 'failed')
                return jsonify({'error': 'No SRTM data available for this location'}), 500

            # 4. Clip and process the SRTM file using the polygon geometry
            polygon_session_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
            os.makedirs(polygon_session_folder, exist_ok=True)
            processed_data = process_srtm_files(srtm_files, geojson_data, polygon_session_folder)
            
            if 'error' in processed_data:
                db_service.update_polygon_status(polygon_id, 'failed')
                return jsonify(processed_data), 500
            
            # 5. Get the final clipped SRTM file path
            clipped_srtm_path = processed_data['clipped_srtm_path']

            # 6. Save the final clipped SRTM data to the polygon session folder
            srtm_file_path = os.path.join(polygon_session_folder, f"{polygon_id}_srtm.tif")
            
            # Copy the clipped SRTM to the named file
            shutil.copy2(clipped_srtm_path, srtm_file_path)
            logger.info(f"Copied clipped SRTM data to: {srtm_file_path}")
            
            # Note: SRTM cache directory should only contain raw, unprocessed SRTM tiles
            # Clipped files belong in polygon session folders, not in the cache
            
            # Add the file path to the response
            processed_data['srtm_file_path'] = srtm_file_path
            
            # Save analysis results to database
            analysis_data = {
                'srtm_path': srtm_file_path,
                'bounds': [min_lon, min_lat, max_lon, max_lat],
                'processed_at': datetime.now().isoformat()
            }
            
            db_service.save_analysis_results(polygon_id, analysis_data)
            db_service.update_polygon_status(polygon_id, 'completed')
            
            # Save SRTM file metadata to database
            srtm_file_result = db_service.save_file_metadata(
                polygon_id=polygon_id,
                file_name=f"{polygon_id}_srtm.tif",
                file_path=srtm_file_path,
                file_type='srtm'
            )
            
            # Cleanup temporary file from processing
            if os.path.exists(clipped_srtm_path):
                 os.remove(clipped_srtm_path)
                 logger.debug(f"Removed temp clipped file: {clipped_srtm_path}")

            # Return the processed SRTM data in the format expected by the frontend
            return jsonify({
                'message': 'Polygon processed successfully. SRTM data clipped and saved.',
                'polygon_id': polygon_id,
                'srtm_file_path': srtm_file_path,
                'image': processed_data.get('image', ''),
                'bounds': {
                    'west': min_lon,
                    'east': max_lon,
                    'north': max_lat,
                    'south': min_lat
                },
                'min_height': processed_data.get('min_height', 0),
                'max_height': processed_data.get('max_height', 0),
                'width': processed_data.get('width', 0),
                'height': processed_data.get('height', 0),
                'database_status': 'saved',
                'file_metadata_status': srtm_file_result
            })

        except Exception as e:
            logger.error(f"Error processing polygon: {str(e)}", exc_info=True)
            db_service.update_polygon_status(polygon_id, 'failed')
            return jsonify({'error': str(e)}), 500
            
    @app.route('/centroid', methods=['POST'])
    def calculate_centroid_route():
        try:
            points = request.json.get('points')
            
            if not points or len(points) < 3:
                return jsonify({'error': 'Not enough points. Need at least 3 for a polygon.'}), 400
            
            # The calculation function remains the same assuming it takes Shapely coordinates
            # Note: The 'calculate_centroid' service function is assumed to correctly handle the 'points' input structure
            # based on how it's used in the original application logic.
            # However, for a GeoJSON Polygon feature, the input should ideally be the GeoJSON object itself.
            # Keeping the old logic for now, but flagging that standard GeoJSON features are usually passed.
            centroid = calculate_centroid(points)
            if not centroid:
                return jsonify({'error': 'Failed to calculate centroid'}), 500
                
            return jsonify({'centroid': centroid})
        except Exception as e:
            logger.exception("Error in calculate_centroid")
            return jsonify({'error': str(e)}), 500