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
        
        logger.info(f"Processing LiDAR terrain for polygon {polygon_id}")
        
        # Use new independent LIDAR processor with CRS transformation
        from services.lidar_processor import process_lidar_dem
        
        results = process_lidar_dem(polygon_geometry, polygon_id)
        
        if 'error' in results:
            return jsonify({
                'status': 'error',
                'message': results['error']
            }), 500
        
        # Save LIDAR analysis results to database (same as SRTM)
        from services.database import DatabaseService
        db_service = DatabaseService()
        
        analysis_data = {
            'final_dem_path': results.get('final_dem_path'),
            'bounds': results.get('bounds'),
            'statistics': results.get('statistics'),
            'image': results.get('image'),
            'data_source': 'lidar'
        }
        
        save_result = db_service.save_analysis_results(polygon_id, analysis_data)
        if save_result and save_result.get('status') == 'success':
            logger.info(f"✅ LIDAR analysis results saved successfully for {polygon_id}")
        else:
            error_message = save_result.get('message', 'save_analysis_results failed') if save_result else 'save_analysis_results returned None'
            logger.error(f"❌ CRITICAL: FAILED to save LIDAR analysis results for {polygon_id}: {error_message}")
            return jsonify({
                'status': 'error',
                'message': f'Failed to save analysis results: {error_message}'
            }), 500
        
        return jsonify({
            'status': 'success',
            'message': 'LiDAR processing completed',
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Error processing LiDAR terrain: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Error: {str(e)}'
        }), 500
