"""
Routes for terrain analysis and processing
"""
import logging
from flask import request, jsonify
import json
import os
from pathlib import Path
from datetime import datetime

from services.terrain import calculate_slopes, visualize_slope, generate_contours, calculate_geomorphons, visualize_geomorphons, calculate_hypsometrically_tinted_hillshade, visualize_hillshade, calculate_aspect, visualize_aspect, calculate_drainage_network, visualize_drainage_network
from utils.config import SAVE_DIRECTORY
from utils.file_io import get_most_recent_polygon
from utils.cors import jsonify_with_cors

logger = logging.getLogger(__name__)

# Import the unified helper directly
from scripts.helpers.dem_file_finder import find_dem_file

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
                return jsonify_with_cors({'error': 'Missing polygon ID parameter'}), 400
                
            polygon_id = data['id']
            logger.info(f"🔍 Processing slopes for polygon ID: {polygon_id}")
            
            # Construct the path to the polygon session folder
            polygon_session_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
            logger.info(f"🔍 Looking for polygon session folder: {polygon_session_folder}")
            
            if not os.path.exists(polygon_session_folder):
                logger.error(f"❌ Polygon session folder not found: {polygon_session_folder}")
                return jsonify_with_cors({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            logger.info(f"✅ Polygon session folder exists: {polygon_session_folder}")
            
            # Find DEM file using unified helper (supports SRTM, LIDAR PT, LIDAR USA)
            from scripts.helpers.dem_file_finder import find_dem_file
            
            input_file = find_dem_file(polygon_session_folder, polygon_id)
            if not input_file:
                logger.error("❌ No DEM data found in polygon session folder")
                return jsonify_with_cors({'error': 'DEM data not found. Please process terrain data first.'}), 400
            
            logger.info(f"✅ Using DEM file: {input_file}")
            
            # Output file in the polygon session folder
            slope_file = os.path.join(polygon_session_folder, f"{polygon_id}_slope.tif")
            
            # Calculate slope
            success = calculate_slopes(input_file, slope_file)
            if not success:
                return jsonify_with_cors({'error': 'Failed to calculate slope'}), 500
            
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
                return jsonify_with_cors({'error': 'Failed to visualize slope data'}), 500
            
            # Add the file paths to the response
            slope_viz['slope_file'] = slope_file
            
            # Save slope analysis results to database
            from services.database import DatabaseService
            db_service = DatabaseService()
            
            # Update the analyses table with slope path
            analysis_data = {
                'slope_path': slope_file,
                'bounds': slope_viz.get('bounds', {}),
                'processed_at': datetime.now().isoformat()
            }
            
            # Update existing analysis record with slope path
            update_result = db_service.update_analysis_paths(polygon_id, analysis_data)
            if update_result.get('status') != 'success':
                logger.warning(f"Failed to update analysis paths: {update_result.get('message', 'Unknown error')}")
            
            # Save slope file metadata to database
            slope_file_result = db_service.save_file_metadata(
                polygon_id=polygon_id,
                file_name=f"{polygon_id}_slope.tif",
                file_path=slope_file,
                file_type='slope'
            )
            
            if slope_file_result.get('status') != 'success':
                logger.warning(f"Failed to save slope file metadata: {slope_file_result.get('message', 'Unknown error')}")
            
            # Try to recalculate statistics if we have all required files
            try:
                stats_result = db_service.recalculate_statistics(polygon_id)
                if stats_result.get('status') == 'success':
                    logger.info("✅ Statistics recalculated successfully after slope processing")
                else:
                    logger.info(f"ℹ️ Statistics not recalculated: {stats_result.get('message', 'Unknown reason')}")
            except Exception as e:
                logger.warning(f"Could not recalculate statistics: {str(e)}")
                
            return jsonify_with_cors(slope_viz)
        except Exception as e:
            logger.error(f"Error processing slopes: {str(e)}", exc_info=True)
            return jsonify_with_cors({'error': str(e)}), 500
    
    @app.route('/generate_contours', methods=['POST'])
    def generate_contours_route():
        try:
            logger.info("============= CONTOUR GENERATION STARTED =============")
            data = request.json
            logger.info(f"Received contour request data: {json.dumps(data, indent=2)}")
            
            # Check for required polygon ID
            if 'id' not in data:
                return jsonify_with_cors({'error': 'Missing polygon ID parameter'}), 400
                
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
                return jsonify_with_cors({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
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
                return jsonify_with_cors({'error': 'SRTM data not found. Please process terrain data first.'}), 400
            
            # Output file in the polygon session folder
            contour_file = os.path.join(polygon_session_folder, f"{polygon_id}_contours.geojson")
            logger.info(f"Contour output file will be: {contour_file}")
            
            # Generate contours
            contours_geojson = generate_contours(input_file, contour_file, interval)
            if not contours_geojson:
                return jsonify_with_cors({'error': 'Failed to generate contours'}), 500
            
            logger.info("============= CONTOUR GENERATION COMPLETED SUCCESSFULLY =============")
            
            # Save contours analysis results to database
            from services.database import DatabaseService
            db_service = DatabaseService()
            
            # Update the analyses table with contours path
            contours_analysis_data = {
                'contours_path': contour_file,
                'bounds': contours_geojson.get('bounds', {}),
                'processed_at': datetime.now().isoformat()
            }
            
            # Update existing analysis record with contours path
            update_result = db_service.update_analysis_paths(polygon_id, contours_analysis_data)
            if update_result.get('status') != 'success':
                logger.warning(f"Failed to update analysis paths: {update_result.get('message', 'Unknown error')}")
            
            # Save contours file metadata to database
            contours_file_result = db_service.save_file_metadata(
                polygon_id=polygon_id,
                file_name=f"{polygon_id}_contours.geojson",
                file_path=contour_file,
                file_type='contours'
            )
            
            if contours_file_result.get('status') != 'success':
                logger.warning(f"Failed to save contours file metadata: {contours_file_result.get('message', 'Unknown error')}")
            
            return jsonify_with_cors({
                'contours': contours_geojson,
                'interval': interval,
                'contour_file': contour_file
            })
        
        except Exception as e:
            logger.error(f"Error in generate_contours: {str(e)}", exc_info=True)
            logger.error("============= CONTOUR GENERATION FAILED =============")
            return jsonify_with_cors({'error': str(e)}), 500
    
    @app.route('/process_geomorphons', methods=['POST'])
    def process_geomorphons():
        try:
            logger.info("🔍 ============ GEOMORPHONS PROCESSING STARTED ============")
            data = request.json
            logger.info(f"🔍 Received geomorphons request data: {json.dumps(data, indent=2)}")
            
            if 'id' not in data:
                logger.error("❌ Missing polygon ID parameter")
                return jsonify_with_cors({'error': 'Missing polygon ID parameter'}), 400
                
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
                return jsonify_with_cors({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            logger.info(f"✅ Polygon session folder exists: {polygon_session_folder}")
            
            # Find DEM file using unified helper (supports SRTM, LIDAR PT, LIDAR USA)
            input_file = find_dem_file(polygon_session_folder, polygon_id)
            if not input_file:
                logger.error("❌ No DEM data found in polygon session folder")
                return jsonify_with_cors({'error': 'DEM data not found. Please process terrain data first.'}), 400
            
            logger.info(f"✅ Using DEM file: {input_file}")
            
            # Output file in the polygon session folder
            geomorphons_file = os.path.join(polygon_session_folder, f"{polygon_id}_geomorphons.tif")
            
            # Calculate geomorphons
            success = calculate_geomorphons(input_file, geomorphons_file, search, threshold, forms)
            if not success:
                return jsonify_with_cors({'error': 'Failed to calculate geomorphons'}), 500
            
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
                return jsonify_with_cors({'error': 'Failed to visualize geomorphons data'}), 500
            
            # Add the file paths to the response
            geomorphons_viz['geomorphons_file'] = geomorphons_file
            
            # Save geomorphons analysis results to database
            from services.database import DatabaseService
            db_service = DatabaseService()
            
            # Update the analyses table with geomorphons path
            geomorphons_analysis_data = {
                'geomorphons_path': geomorphons_file,
                'bounds': geomorphons_viz.get('bounds', {}),
                'processed_at': datetime.now().isoformat()
            }
            
            # Update existing analysis record with geomorphons path
            update_result = db_service.update_analysis_paths(polygon_id, geomorphons_analysis_data)
            if update_result.get('status') != 'success':
                logger.warning(f"Failed to update analysis paths: {update_result.get('message', 'Unknown error')}")
            
            # Save geomorphons file metadata to database
            geomorphons_file_result = db_service.save_file_metadata(
                polygon_id=polygon_id,
                file_name=f"{polygon_id}_geomorphons.tif",
                file_path=geomorphons_file,
                file_type='geomorphons'
            )
            
            if geomorphons_file_result.get('status') != 'success':
                logger.warning(f"Failed to save geomorphons file metadata: {geomorphons_file_result.get('message', 'Unknown error')}")
                
            return jsonify_with_cors(geomorphons_viz)
        except Exception as e:
            logger.error(f"Error processing geomorphons: {str(e)}", exc_info=True)
            return jsonify_with_cors({'error': str(e)}), 500
    
    @app.route('/process_hillshade', methods=['POST'])
    def process_hillshade():
        try:
            logger.info("🔍 ============ HILLSHADE PROCESSING STARTED ============")
            data = request.json
            logger.info(f"🔍 Received hillshade request data: {json.dumps(data, indent=2)}")
            
            if 'id' not in data:
                logger.error("❌ Missing polygon ID parameter")
                return jsonify_with_cors({'error': 'Missing polygon ID parameter'}), 400
                
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
                return jsonify_with_cors({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            logger.info(f"✅ Polygon session folder exists: {polygon_session_folder}")
            
            # Find DEM file using unified helper (supports SRTM, LIDAR PT, LIDAR USA)
            input_file = find_dem_file(polygon_session_folder, polygon_id)
            if not input_file:
                logger.error("❌ No DEM data found in polygon session folder")
                return jsonify_with_cors({'error': 'DEM data not found. Please process terrain data first.'}), 400
            
            logger.info(f"✅ Using DEM file: {input_file}")
            
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
                return jsonify_with_cors({'error': 'Failed to calculate hillshade'}), 500
            
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
                return jsonify_with_cors({'error': 'Failed to visualize hillshade data'}), 500
            
            # Add the file paths to the response
            hillshade_viz['hillshade_file'] = hillshade_file
            
            # Save hillshade analysis results to database
            from services.database import DatabaseService
            db_service = DatabaseService()
            
            # Update the analyses table with hillshade path
            hillshade_analysis_data = {
                'hillshade_path': hillshade_file,
                'bounds': hillshade_viz.get('bounds', {}),
                'processed_at': datetime.now().isoformat()
            }
            
            # Update existing analysis record with hillshade path
            update_result = db_service.update_analysis_paths(polygon_id, hillshade_analysis_data)
            if update_result.get('status') != 'success':
                logger.warning(f"Failed to update analysis paths: {update_result.get('message', 'Unknown error')}")
            
            # Save hillshade file metadata to database
            hillshade_file_result = db_service.save_file_metadata(
                polygon_id=polygon_id,
                file_name=f"{polygon_id}_hillshade.tif",
                file_path=hillshade_file,
                file_type='hillshade'
            )
            
            if hillshade_file_result.get('status') != 'success':
                logger.warning(f"Failed to save hillshade file metadata: {hillshade_file_result.get('message', 'Unknown error')}")
                
            return jsonify_with_cors(hillshade_viz)
        except Exception as e:
            logger.error(f"Error processing hillshade: {str(e)}", exc_info=True)
            return jsonify_with_cors({'error': str(e)}), 500
    
    @app.route('/process_aspect', methods=['POST'])
    def process_aspect():
        try:
            logger.info("🔍 ============ ASPECT PROCESSING STARTED ============")
            data = request.json
            logger.info(f"🔍 Received aspect request data: {json.dumps(data, indent=2)}")
            
            if 'id' not in data:
                logger.error("❌ Missing polygon ID parameter")
                return jsonify_with_cors({'error': 'Missing polygon ID parameter'}), 400
                
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
                return jsonify_with_cors({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            logger.info(f"✅ Polygon session folder exists: {polygon_session_folder}")
            
            # Find DEM file using unified helper (supports SRTM, LIDAR PT, LIDAR USA)
            input_file = find_dem_file(polygon_session_folder, polygon_id)
            if not input_file:
                logger.error("❌ No DEM data found in polygon session folder")
                return jsonify_with_cors({'error': 'DEM data not found. Please process terrain data first.'}), 400
            
            logger.info(f"✅ Using DEM file: {input_file}")
            
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
                return jsonify_with_cors({'error': 'Failed to calculate aspect'}), 500
            
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
                return jsonify_with_cors({'error': 'Failed to visualize aspect data'}), 500
            
            # Add the file paths to the response
            aspect_viz['aspect_file'] = aspect_file
            
            # Save aspect analysis results to database
            from services.database import DatabaseService
            db_service = DatabaseService()
            
            # Update the analyses table with aspect path
            aspect_analysis_data = {
                'aspect_path': aspect_file,
                'bounds': aspect_viz.get('bounds', {}),
                'processed_at': datetime.now().isoformat()
            }
            
            # Update existing analysis record with aspect path
            update_result = db_service.update_analysis_paths(polygon_id, aspect_analysis_data)
            if update_result.get('status') != 'success':
                logger.warning(f"Failed to update analysis paths: {update_result.get('message', 'Unknown error')}")
            
            # Save aspect file metadata to database
            aspect_file_result = db_service.save_file_metadata(
                polygon_id=polygon_id,
                file_name=f"{polygon_id}_aspect.tif",
                file_path=aspect_file,
                file_type='aspect'
            )
            
            if aspect_file_result.get('status') != 'success':
                logger.warning(f"Failed to save aspect file metadata: {aspect_file_result.get('message', 'Unknown error')}")
            
            # Try to recalculate statistics if we have all required files
            try:
                stats_result = db_service.recalculate_statistics(polygon_id)
                if stats_result.get('status') == 'success':
                    logger.info("✅ Statistics recalculated successfully after aspect processing")
                else:
                    logger.info(f"ℹ️ Statistics not recalculated: {stats_result.get('message', 'Unknown reason')}")
            except Exception as e:
                logger.warning(f"Could not recalculate statistics: {str(e)}")
                
            return jsonify_with_cors(aspect_viz)
        except Exception as e:
            logger.error(f"Error processing aspect: {str(e)}", exc_info=True)
            return jsonify_with_cors({'error': str(e)}), 500

    @app.route('/process_drainage_network', methods=['POST'])
    def process_drainage_network():
        try:
            logger.info("🔍 ============ DRAINAGE NETWORK PROCESSING STARTED ============")
            data = request.json
            logger.info(f"🔍 Received drainage network request data: {json.dumps(data, indent=2)}")
            
            if 'id' not in data:
                logger.error("❌ Missing polygon ID parameter")
                return jsonify_with_cors({'error': 'Missing polygon ID parameter'}), 400
                
            polygon_id = data['id']
            logger.info(f"🔍 Processing drainage network for polygon ID: {polygon_id}")
            
            # Construct the path to the polygon session folder
            polygon_session_folder = os.path.join(SAVE_DIRECTORY, "polygon_sessions", polygon_id)
            logger.info(f"🔍 Looking for polygon session folder: {polygon_session_folder}")
            
            if not os.path.exists(polygon_session_folder):
                logger.error(f"❌ Polygon session folder not found: {polygon_session_folder}")
                return jsonify_with_cors({'error': f'Polygon session folder not found for ID: {polygon_id}'}), 404
            
            logger.info(f"✅ Polygon session folder exists: {polygon_session_folder}")
            
            # Check if DEM file exists (try both SRTM and LIDAR patterns)
            srtm_file = find_dem_file(polygon_session_folder, polygon_id)
            if not srtm_file:
                return jsonify_with_cors({'error': 'DEM file not found. Please process elevation data first.'}), 404
            
            logger.info(f"✅ DEM file found: {srtm_file}")
            
            # Set up output file path
            drainage_file = os.path.join(polygon_session_folder, f"{polygon_id}_drainage_network.tif")
            logger.info(f"🔍 Output drainage network file: {drainage_file}")
            
            # Calculate drainage network
            logger.info("🔍 Starting drainage network calculation...")
            success = calculate_drainage_network(srtm_file, drainage_file)
            
            if not success:
                logger.error("❌ Failed to calculate drainage network")
                return jsonify_with_cors({'error': 'Failed to calculate drainage network'}), 500
            
            logger.info("✅ Drainage network calculation completed successfully")
            
            # Load polygon data for masking
            polygon_data = None
            try:
                polygon_file = os.path.join(polygon_session_folder, f"{polygon_id}.geojson")
                if os.path.exists(polygon_file):
                    with open(polygon_file, 'r') as f:
                        polygon_data = json.load(f)
                    logger.info("✅ Loaded polygon data for masking")
                else:
                    logger.warning("⚠️ No polygon file found, proceeding without masking")
            except Exception as e:
                logger.warning(f"⚠️ Could not load polygon data: {str(e)}")
            
            # Visualize drainage network
            logger.info("🔍 Starting drainage network visualization...")
            drainage_viz = visualize_drainage_network(drainage_file, polygon_data)
            
            if not drainage_viz:
                logger.error("❌ Failed to visualize drainage network data")
                return jsonify_with_cors({'error': 'Failed to visualize drainage network data'}), 500
            
            logger.info("✅ Drainage network visualization completed successfully")
            
            # Add the file paths to the response
            drainage_viz['drainage_file'] = drainage_file
            
            # Save drainage analysis results to database
            from services.database import DatabaseService
            db_service = DatabaseService()
            
            # Update the analyses table with drainage path
            drainage_analysis_data = {
                'drainage_path': drainage_file,
                'bounds': drainage_viz.get('bounds', {}),
                'processed_at': datetime.now().isoformat()
            }
            
            # Update existing analysis record with drainage path
            update_result = db_service.update_analysis_paths(polygon_id, drainage_analysis_data)
            if update_result.get('status') != 'success':
                logger.warning(f"Failed to update analysis paths: {update_result.get('message', 'Unknown error')}")
            
            # Save drainage file metadata to database
            drainage_file_result = db_service.save_file_metadata(
                polygon_id=polygon_id,
                file_name=f"{polygon_id}_drainage_network.tif",
                file_path=drainage_file,
                file_type='drainage'
            )
            
            if drainage_file_result.get('status') != 'success':
                logger.warning(f"Failed to save drainage file metadata: {drainage_file_result.get('message', 'Unknown error')}")
                
            return jsonify_with_cors(drainage_viz)
        except Exception as e:
            logger.error(f"Error processing drainage network: {str(e)}", exc_info=True)
            return jsonify_with_cors({'error': str(e)}), 500