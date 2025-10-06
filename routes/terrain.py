"""
Routes for terrain analysis and processing
"""
import logging
from flask import request, jsonify
import json
import os
from pathlib import Path

from services.terrain import calculate_slopes, visualize_slope, generate_contours
from utils.config import SAVE_DIRECTORY
from utils.file_io import get_most_recent_polygon

logger = logging.getLogger(__name__)

def register_routes(app):
    """
    Register all terrain analysis related routes
    
    Args:
        app: Flask application instance
    """
    @app.route('/process_slopes', methods=['POST'])
    def process_slopes():
        try:
            data = request.json
            if 'id' not in data:
                return jsonify({'error': 'Missing polygon ID parameter'}), 400
                
            polygon_id = data['id']
            logger.info(f"Processing slopes for polygon ID: {polygon_id}")
            
            # Construct the path to the polygon session folder
            polygon_session_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
            if not os.path.exists(polygon_session_folder):
                return jsonify({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            # Look for the SRTM data in the polygon session folder
            srtm_file = os.path.join(polygon_session_folder, f"{polygon_id}_srtm.tif")
            if os.path.exists(srtm_file):
                input_file = srtm_file
                logger.info(f"Using SRTM file from polygon session: {input_file}")
            else:
                # If no SRTM file in the session folder, look for clipped_srtm.tif
                clipped_srtm = os.path.join(polygon_session_folder, "clipped_srtm.tif")
                if os.path.exists(clipped_srtm):
                    input_file = clipped_srtm
                    logger.info(f"Using clipped SRTM file from polygon session: {input_file}")
                else:
                    # Check in the srtms directory as fallback
                    srtms_dir = SAVE_DIRECTORY / "srtms"
                    srtms_dir.mkdir(exist_ok=True)  # Ensure srtms directory exists
                    data_input_file = srtms_dir / "clipped_srtm.tif"
                    
                    if data_input_file.exists():
                        input_file = data_input_file
                        logger.info(f"Using clipped SRTM file from data directory: {input_file}")
                    else:
                        # If no SRTM file found, return error
                        return jsonify({'error': 'SRTM data not found. Please process terrain data first.'}), 400
            
            # Output file in the polygon session folder
            slope_file = os.path.join(polygon_session_folder, f"{polygon_id}_slope.tif")
            
            # Calculate slope
            success = calculate_slopes(input_file, slope_file)
            if not success:
                return jsonify({'error': 'Failed to calculate slope'}), 500
            
            # Load the polygon data
            polygon_file = os.path.join(polygon_session_folder, f"{polygon_id}.geojson")
            polygon_data = None
            if os.path.exists(polygon_file):
                try:
                    with open(polygon_file, 'r') as f:
                        polygon_data = json.load(f)
                        logger.info(f"Loaded polygon data for masking from: {polygon_file}")
                except Exception as e:
                    logger.error(f"Error loading polygon data: {str(e)}")
                    # Continue without polygon masking
            
            # Visualize the slope data
            slope_viz = visualize_slope(slope_file, polygon_data)
            if not slope_viz:
                return jsonify({'error': 'Failed to visualize slope data'}), 500
            
            # Add the file paths to the response
            slope_viz['slope_file'] = slope_file
                
            return jsonify(slope_viz)
        except Exception as e:
            logger.error(f"Error processing slopes: {str(e)}", exc_info=True)
            return jsonify({'error': str(e)}), 500
    
    @app.route('/generate_contours', methods=['POST'])
    def generate_contours_route():
        try:
            logger.info("============= CONTOUR GENERATION STARTED =============")
            data = request.json
            logger.info(f"Received contour request data: {json.dumps(data, indent=2)}")
            
            # Check for required polygon ID
            if 'id' not in data:
                return jsonify({'error': 'Missing polygon ID parameter'}), 400
                
            polygon_id = data['id']
            logger.info(f"Generating contours for polygon ID: {polygon_id}")
            
            # Get contour interval (optional with default)
            if 'interval' not in data:
                interval = 10  # Default contour interval (meters)
                logger.info(f"No interval provided, using default: {interval}m")
            else:
                interval = float(data['interval'])
                logger.info(f"Using provided interval: {interval}m")
            
            # Construct the path to the polygon session folder
            polygon_session_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
            if not os.path.exists(polygon_session_folder):
                return jsonify({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            # Look for the SRTM data in the polygon session folder
            input_file = None
            possible_srtm_files = [
                os.path.join(polygon_session_folder, f"{polygon_id}_srtm.tif"),
                os.path.join(polygon_session_folder, "clipped_srtm.tif")
            ]
            
            for srtm_file in possible_srtm_files:
                if os.path.exists(srtm_file):
                    input_file = srtm_file
                    logger.info(f"Using SRTM file for contours: {input_file}")
                    break
            
            # If no SRTM file in the session folder, check srtms directory as fallback
            if not input_file:
                srtms_dir = SAVE_DIRECTORY / "srtms"
                srtms_dir.mkdir(exist_ok=True)  # Ensure srtms directory exists
                data_input_file = srtms_dir / "clipped_srtm.tif"
                
                if data_input_file.exists():
                    input_file = data_input_file
                    logger.info(f"Using clipped SRTM file from data directory: {input_file}")
                else:
                    # If no SRTM file found, return error
                    return jsonify({'error': 'SRTM data not found. Please process terrain data first.'}), 400
            
            # Output file in the polygon session folder
            contour_file = os.path.join(polygon_session_folder, f"{polygon_id}_contours.geojson")
            logger.info(f"Contour output file will be: {contour_file}")
            
            # Generate contours
            contours_geojson = generate_contours(input_file, contour_file, interval)
            if not contours_geojson:
                return jsonify({'error': 'Failed to generate contours'}), 500
            
            logger.info("============= CONTOUR GENERATION COMPLETED SUCCESSFULLY =============")
            
            return jsonify({
                'contours': contours_geojson,
                'interval': interval,
                'contour_file': contour_file
            })
        
        except Exception as e:
            logger.error(f"Error in generate_contours: {str(e)}", exc_info=True)
            logger.error("============= CONTOUR GENERATION FAILED =============")
            return jsonify({'error': str(e)}), 500 