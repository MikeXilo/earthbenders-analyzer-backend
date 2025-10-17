"""
Routes for LiDAR data processing and availability checking
"""
import os
import glob
import logging
import rasterio
from flask import Blueprint, request, jsonify
from shapely.geometry import box
from shapely.geometry import shape as shapely_shape

logger = logging.getLogger(__name__)

# Create blueprint
lidar_bp = Blueprint('lidar', __name__)

def register_routes(app):
    """Register LiDAR routes with Flask app"""
    app.register_blueprint(lidar_bp)

@lidar_bp.route('/api/lidar/check', methods=['POST'])
def check_lidar_availability():
    """
    Check if LiDAR tiles are available for the given polygon bounds
    
    Expected request body:
    {
        "bounds": {
            "minLon": float,
            "minLat": float, 
            "maxLon": float,
            "maxLat": float
        }
    }
    
    Returns:
    {
        "available": bool,
        "tiles": list,
        "message": str
    }
    """
    try:
        data = request.get_json()
        if not data or 'bounds' not in data:
            return jsonify({
                'available': False,
                'tiles': [],
                'message': 'Invalid request: bounds required'
            }), 400
        
        bounds = data['bounds']
        min_lon = bounds.get('minLon')
        min_lat = bounds.get('minLat')
        max_lon = bounds.get('maxLon')
        max_lat = bounds.get('maxLat')
        
        if None in [min_lon, min_lat, max_lon, max_lat]:
            return jsonify({
                'available': False,
                'tiles': [],
                'message': 'Invalid bounds: all coordinates required'
            }), 400
        
        logger.info(f"Checking LiDAR availability for bounds: {bounds}")
        
        # Check for LiDAR tiles in the LidarPt folder
        lidar_folder = "/app/data/LidarPt"
        if not os.path.exists(lidar_folder):
            logger.warning(f"LiDAR folder does not exist: {lidar_folder}")
            return jsonify({
                'available': False,
                'tiles': [],
                'message': 'LiDAR folder not found'
            })
        
        # Find all GeoTIFF files in LidarPt folder
        lidar_files = glob.glob(os.path.join(lidar_folder, "*.tif"))
        logger.info(f"Found {len(lidar_files)} LiDAR files in {lidar_folder}")
        
        if not lidar_files:
            return jsonify({
                'available': False,
                'tiles': [],
                'message': 'No LiDAR tiles found'
            })
        
        # Check which tiles intersect with the polygon bounds
        intersecting_tiles = []
        polygon_bounds = box(min_lon, min_lat, max_lon, max_lat)
        
        for tile_path in lidar_files:
            try:
                with rasterio.open(tile_path) as src:
                    # Get tile bounds
                    tile_bounds = src.bounds
                    tile_box = box(tile_bounds.left, tile_bounds.bottom, 
                                 tile_bounds.right, tile_bounds.top)
                    
                    # Check if tile intersects with polygon bounds
                    if polygon_bounds.intersects(tile_box):
                        intersecting_tiles.append({
                            'path': tile_path,
                            'filename': os.path.basename(tile_path),
                            'bounds': {
                                'left': tile_bounds.left,
                                'bottom': tile_bounds.bottom,
                                'right': tile_bounds.right,
                                'top': tile_bounds.top
                            }
                        })
                        logger.info(f"Found intersecting tile: {os.path.basename(tile_path)}")
                        
            except Exception as e:
                logger.error(f"Error reading tile {tile_path}: {e}")
                continue
        
        available = len(intersecting_tiles) > 0
        
        return jsonify({
            'available': available,
            'tiles': intersecting_tiles,
            'message': f"Found {len(intersecting_tiles)} intersecting LiDAR tiles" if available else "No intersecting LiDAR tiles found"
        })
        
    except Exception as e:
        logger.error(f"Error checking LiDAR availability: {e}")
        return jsonify({
            'available': False,
            'tiles': [],
            'message': f'Error: {str(e)}'
        }), 500

@lidar_bp.route('/api/lidar/process', methods=['POST'])
def process_lidar_terrain():
    """
    Process terrain analysis using LiDAR data with CRS transformation
    
    Expected request body:
    {
        "polygon": GeoJSON geometry,
        "polygon_id": "unique_id"
    }
    """
    try:
        data = request.get_json()
        if not data or 'polygon' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Polygon geometry required'
            }), 400
        
        polygon_geometry = data['polygon']
        polygon_id = data.get('polygon_id', 'default_polygon')
        user_id = data.get('user_id', None)  # Extract user_id for database saving
        
        logger.info(f"🚀 LIDAR ROUTE CALLED - Processing LiDAR terrain for polygon {polygon_id}")
        logger.info(f"📊 LIDAR Request data: {data}")
        
        # PHASE 1: LIDAR-specific preparation (CRS conversion and clipping)
        logger.info("PHASE 1: Starting LIDAR data preparation (merge, reproject, clip)")
        from services.lidar_processor import process_lidar_dem
        
        clipped_lidar_path = process_lidar_dem(polygon_geometry, polygon_id)
        
        if not clipped_lidar_path:
            return jsonify({
                'status': 'error',
                'message': 'LIDAR preparation failed to produce a clipped DEM file'
            }), 500
            
        logger.info(f"PHASE 1: LIDAR DEM ready at {clipped_lidar_path}. Proceeding to unified analysis.")
        
        # PHASE 2: Unified analysis & visualization (using proven SRTM logic)
        logger.info("PHASE 2: Starting unified analysis & visualization (using SRTM logic)")
        from services.srtm import process_srtm_files
        
        # Use SRTM pipeline with LIDAR file
        results = process_srtm_files(
            [clipped_lidar_path],  # Pass as list to match SRTM function signature
            polygon_geometry,
            f"/app/data/polygon_sessions/{polygon_id}"
        )
        
        if not results or not results.get('image'):
            return jsonify({
                'status': 'error',
                'message': 'Unified analysis failed to produce a valid visualization overlay'
            }), 500
        
        # PHASE 3: Calculate statistics and save to database
        logger.info("PHASE 3: Calculating statistics and saving LIDAR analysis results to database")
        from services.database import DatabaseService
        from services.statistics import calculate_terrain_statistics
        db_service = DatabaseService()
        
        # Calculate statistics for LIDAR data
        logger.info("Calculating LIDAR terrain statistics...")
        statistics = calculate_terrain_statistics(
            srtm_path=results.get('clipped_srtm_path'),
            slope_path=None,  # LIDAR doesn't have slope/aspect files yet
            aspect_path=None,
            bounds=results.get('bounds', {})
        )
        
        analysis_data = {
            'srtm_path': results.get('clipped_srtm_path'),
            'bounds': results.get('bounds'),
            'statistics': statistics,
            'image': results.get('image'),
            'data_source': 'lidar'
        }
        
        save_result = db_service.save_analysis_results(polygon_id, analysis_data, user_id)
        if save_result and save_result.get('status') == 'success':
            logger.info(f"✅ LIDAR analysis results saved successfully for {polygon_id}")
        else:
            error_message = save_result.get('message', 'save_analysis_results failed') if save_result else 'save_analysis_results returned None'
            logger.error(f"❌ CRITICAL: FAILED to save LIDAR analysis results for {polygon_id}: {error_message}")
            return jsonify({
                'status': 'error',
                'message': f'Failed to save analysis results: {error_message}'
            }), 500
        
        # Results are already in proven SRTM format - return directly
        return jsonify({
            'status': 'success',
            'message': 'LIDAR terrain analysis completed successfully via unified pipeline',
            'polygonId': polygon_id,
            'min_height': results.get('min_height'),
            'max_height': results.get('max_height'),
            'bounds': results.get('bounds'),
            'image': results.get('image'),
            'analysis_files': {
                'elevation': results.get('clipped_srtm_path'),
                'slope': None,
                'aspect': None
            }
        })
        
    except Exception as e:
        logger.error(f"Error processing LiDAR terrain: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Error: {str(e)}'
        }), 500
