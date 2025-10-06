"""
Routes for terrain analysis and processing
"""
import logging
from flask import request, jsonify
import json
import os
from pathlib import Path

from services.terrain import calculate_slopes, visualize_slope, generate_contours, calculate_geomorphons, visualize_geomorphons, calculate_hypsometrically_tinted_hillshade, visualize_hillshade, calculate_aspect, visualize_aspect
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
            logger.info("🔍 ============ SLOPE PROCESSING STARTED ============")
            data = request.json
            logger.info(f"🔍 Received slope request data: {json.dumps(data, indent=2)}")
            
            if 'id' not in data:
                logger.error("❌ Missing polygon ID parameter")
                return jsonify({'error': 'Missing polygon ID parameter'}), 400
                
            polygon_id = data['id']
            logger.info(f"🔍 Processing slopes for polygon ID: {polygon_id}")
            
            # Construct the path to the polygon session folder
            polygon_session_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
            logger.info(f"🔍 Looking for polygon session folder: {polygon_session_folder}")
            
            if not os.path.exists(polygon_session_folder):
                logger.error(f"❌ Polygon session folder not found: {polygon_session_folder}")
                return jsonify({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            logger.info(f"✅ Polygon session folder exists: {polygon_session_folder}")
            
            # Look for the SRTM data in the polygon session folder
            srtm_file = os.path.join(polygon_session_folder, f"{polygon_id}_srtm.tif")
            logger.info(f"🔍 Looking for SRTM file: {srtm_file}")
            
            if os.path.exists(srtm_file):
                input_file = srtm_file
                logger.info(f"✅ Using SRTM file from polygon session: {input_file}")
            else:
                logger.info(f"❌ SRTM file not found: {srtm_file}")
                # If no SRTM file in the session folder, look for clipped_srtm.tif
                clipped_srtm = os.path.join(polygon_session_folder, "clipped_srtm.tif")
                logger.info(f"🔍 Looking for clipped SRTM file: {clipped_srtm}")
                
                if os.path.exists(clipped_srtm):
                    input_file = clipped_srtm
                    logger.info(f"✅ Using clipped SRTM file from polygon session: {input_file}")
                else:
                    logger.error("❌ No SRTM data found in polygon session folder")
                    # SRTM cache directory should only contain raw tiles, not clipped files
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
                # SRTM cache directory should only contain raw tiles, not clipped files
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
    
    @app.route('/process_geomorphons', methods=['POST'])
    def process_geomorphons():
        try:
            logger.info("🔍 ============ GEOMORPHONS PROCESSING STARTED ============")
            data = request.json
            logger.info(f"🔍 Received geomorphons request data: {json.dumps(data, indent=2)}")
            
            if 'id' not in data:
                logger.error("❌ Missing polygon ID parameter")
                return jsonify({'error': 'Missing polygon ID parameter'}), 400
                
            polygon_id = data['id']
            logger.info(f"🔍 Processing geomorphons for polygon ID: {polygon_id}")
            
            # Get geomorphons parameters (optional with defaults)
            search = data.get('search', 50)  # Default search distance
            threshold = data.get('threshold', 0.0)  # Default flatness threshold
            forms = data.get('forms', True)  # Default to common landforms
            
            logger.info(f"🔍 Geomorphons parameters - search: {search}, threshold: {threshold}, forms: {forms}")
            
            # Construct the path to the polygon session folder
            polygon_session_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
            logger.info(f"🔍 Looking for polygon session folder: {polygon_session_folder}")
            
            if not os.path.exists(polygon_session_folder):
                logger.error(f"❌ Polygon session folder not found: {polygon_session_folder}")
                return jsonify({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            logger.info(f"✅ Polygon session folder exists: {polygon_session_folder}")
            
            # Look for the SRTM data in the polygon session folder
            srtm_file = os.path.join(polygon_session_folder, f"{polygon_id}_srtm.tif")
            logger.info(f"🔍 Looking for SRTM file: {srtm_file}")
            
            if os.path.exists(srtm_file):
                input_file = srtm_file
                logger.info(f"✅ Using SRTM file from polygon session: {input_file}")
            else:
                logger.info(f"❌ SRTM file not found: {srtm_file}")
                # If no SRTM file in the session folder, look for clipped_srtm.tif
                clipped_srtm = os.path.join(polygon_session_folder, "clipped_srtm.tif")
                logger.info(f"🔍 Looking for clipped SRTM file: {clipped_srtm}")
                
                if os.path.exists(clipped_srtm):
                    input_file = clipped_srtm
                    logger.info(f"✅ Using clipped SRTM file from polygon session: {input_file}")
                else:
                    logger.error("❌ No SRTM data found in polygon session folder")
                    return jsonify({'error': 'SRTM data not found. Please process terrain data first.'}), 400
            
            # Output file in the polygon session folder
            geomorphons_file = os.path.join(polygon_session_folder, f"{polygon_id}_geomorphons.tif")
            
            # Calculate geomorphons
            success = calculate_geomorphons(input_file, geomorphons_file, search, threshold, forms)
            if not success:
                return jsonify({'error': 'Failed to calculate geomorphons'}), 500
            
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
            
            # Visualize the geomorphons data
            geomorphons_viz = visualize_geomorphons(geomorphons_file, polygon_data)
            if not geomorphons_viz:
                return jsonify({'error': 'Failed to visualize geomorphons data'}), 500
            
            # Add the file paths to the response
            geomorphons_viz['geomorphons_file'] = geomorphons_file
                
            return jsonify(geomorphons_viz)
        except Exception as e:
            logger.error(f"Error processing geomorphons: {str(e)}", exc_info=True)
            return jsonify({'error': str(e)}), 500
    
    @app.route('/process_hillshade', methods=['POST'])
    def process_hillshade():
        try:
            logger.info("🔍 ============ HILLSHADE PROCESSING STARTED ============")
            data = request.json
            logger.info(f"🔍 Received hillshade request data: {json.dumps(data, indent=2)}")
            
            if 'id' not in data:
                logger.error("❌ Missing polygon ID parameter")
                return jsonify({'error': 'Missing polygon ID parameter'}), 400
                
            polygon_id = data['id']
            logger.info(f"🔍 Processing hillshade for polygon ID: {polygon_id}")
            
            # Get hillshade parameters (optional with defaults)
            altitude = data.get('altitude', 45.0)  # Default sun altitude
            hs_weight = data.get('hs_weight', 0.5)  # Default hillshade weight
            brightness = data.get('brightness', 0.5)  # Default brightness
            atmospheric = data.get('atmospheric', 0.0)  # Default atmospheric effects
            palette = data.get('palette', 'atlas')  # Default palette
            zfactor = data.get('zfactor', None)  # Optional z-factor
            
            logger.info(f"🔍 Hillshade parameters - altitude: {altitude}, hs_weight: {hs_weight}, brightness: {brightness}, atmospheric: {atmospheric}, palette: {palette}")
            
            # Construct the path to the polygon session folder
            polygon_session_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
            logger.info(f"🔍 Looking for polygon session folder: {polygon_session_folder}")
            
            if not os.path.exists(polygon_session_folder):
                logger.error(f"❌ Polygon session folder not found: {polygon_session_folder}")
                return jsonify({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            logger.info(f"✅ Polygon session folder exists: {polygon_session_folder}")
            
            # Look for the SRTM data in the polygon session folder
            srtm_file = os.path.join(polygon_session_folder, f"{polygon_id}_srtm.tif")
            logger.info(f"🔍 Looking for SRTM file: {srtm_file}")
            
            if os.path.exists(srtm_file):
                input_file = srtm_file
                logger.info(f"✅ Using SRTM file from polygon session: {input_file}")
            else:
                logger.info(f"❌ SRTM file not found: {srtm_file}")
                # If no SRTM file in the session folder, look for clipped_srtm.tif
                clipped_srtm = os.path.join(polygon_session_folder, "clipped_srtm.tif")
                logger.info(f"🔍 Looking for clipped SRTM file: {clipped_srtm}")
                
                if os.path.exists(clipped_srtm):
                    input_file = clipped_srtm
                    logger.info(f"✅ Using clipped SRTM file from polygon session: {input_file}")
                else:
                    logger.error("❌ No SRTM data found in polygon session folder")
                    return jsonify({'error': 'SRTM data not found. Please process terrain data first.'}), 400
            
            # Output file in the polygon session folder
            hillshade_file = os.path.join(polygon_session_folder, f"{polygon_id}_hillshade.tif")
            
            # Calculate hillshade
            success = calculate_hypsometrically_tinted_hillshade(
                input_file, 
                hillshade_file, 
                altitude=altitude,
                hs_weight=hs_weight,
                brightness=brightness,
                atmospheric=atmospheric,
                palette=palette,
                zfactor=zfactor
            )
            if not success:
                return jsonify({'error': 'Failed to calculate hillshade'}), 500
            
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
            
            # Visualize the hillshade data
            hillshade_viz = visualize_hillshade(hillshade_file, polygon_data)
            if not hillshade_viz:
                return jsonify({'error': 'Failed to visualize hillshade data'}), 500
            
            # Add the file paths to the response
            hillshade_viz['hillshade_file'] = hillshade_file
                
            return jsonify(hillshade_viz)
        except Exception as e:
            logger.error(f"Error processing hillshade: {str(e)}", exc_info=True)
            return jsonify({'error': str(e)}), 500
    
    @app.route('/process_aspect', methods=['POST'])
    def process_aspect():
        try:
            logger.info("🔍 ============ ASPECT PROCESSING STARTED ============")
            data = request.json
            logger.info(f"🔍 Received aspect request data: {json.dumps(data, indent=2)}")
            
            if 'id' not in data:
                logger.error("❌ Missing polygon ID parameter")
                return jsonify({'error': 'Missing polygon ID parameter'}), 400
                
            polygon_id = data['id']
            logger.info(f"🔍 Processing aspect for polygon ID: {polygon_id}")
            
            # Get aspect parameters (optional with defaults)
            convention = data.get('convention', 'azimuth')  # Default azimuth convention
            gradient_alg = data.get('gradient_alg', 'Horn')  # Default Horn algorithm
            zero_for_flat = data.get('zero_for_flat', False)  # Default false
            
            logger.info(f"🔍 Aspect parameters - convention: {convention}, gradient_alg: {gradient_alg}, zero_for_flat: {zero_for_flat}")
            
            # Construct the path to the polygon session folder
            polygon_session_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
            logger.info(f"🔍 Looking for polygon session folder: {polygon_session_folder}")
            
            if not os.path.exists(polygon_session_folder):
                logger.error(f"❌ Polygon session folder not found: {polygon_session_folder}")
                return jsonify({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            logger.info(f"✅ Polygon session folder exists: {polygon_session_folder}")
            
            # Look for the SRTM data in the polygon session folder
            srtm_file = os.path.join(polygon_session_folder, f"{polygon_id}_srtm.tif")
            logger.info(f"🔍 Looking for SRTM file: {srtm_file}")
            
            if os.path.exists(srtm_file):
                input_file = srtm_file
                logger.info(f"✅ Using SRTM file from polygon session: {input_file}")
            else:
                logger.info(f"❌ SRTM file not found: {srtm_file}")
                # If no SRTM file in the session folder, look for clipped_srtm.tif
                clipped_srtm = os.path.join(polygon_session_folder, "clipped_srtm.tif")
                logger.info(f"🔍 Looking for clipped SRTM file: {clipped_srtm}")
                
                if os.path.exists(clipped_srtm):
                    input_file = clipped_srtm
                    logger.info(f"✅ Using clipped SRTM file from polygon session: {input_file}")
                else:
                    logger.error("❌ No SRTM data found in polygon session folder")
                    return jsonify({'error': 'SRTM data not found. Please process terrain data first.'}), 400
            
            # Output file in the polygon session folder
            aspect_file = os.path.join(polygon_session_folder, f"{polygon_id}_aspect.tif")
            
            # Calculate aspect
            success = calculate_aspect(
                input_file, 
                aspect_file, 
                convention=convention,
                gradient_alg=gradient_alg,
                zero_for_flat=zero_for_flat
            )
            if not success:
                return jsonify({'error': 'Failed to calculate aspect'}), 500
            
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
            
            # Visualize the aspect data
            aspect_viz = visualize_aspect(aspect_file, polygon_data)
            if not aspect_viz:
                return jsonify({'error': 'Failed to visualize aspect data'}), 500
            
            # Add the file paths to the response
            aspect_viz['aspect_file'] = aspect_file
                
            return jsonify(aspect_viz)
        except Exception as e:
            logger.error(f"Error processing aspect: {str(e)}", exc_info=True)
            return jsonify({'error': str(e)}), 500 