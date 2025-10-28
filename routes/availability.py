# Backend availability check endpoints
# Add these to your backend routes

from flask import Blueprint, request, jsonify
import json
from typing import Dict, Any

# Create blueprint for availability checks
availability_bp = Blueprint('availability', __name__, url_prefix='/api')

def detect_geographic_region(polygon_geometry: Dict[str, Any]) -> str:
    """
    Detect geographic region based on polygon geometry
    Returns: 'portugal', 'us', or 'global'
    """
    try:
        # Extract coordinates from GeoJSON polygon
        if polygon_geometry.get('type') == 'Polygon':
            coordinates = polygon_geometry['coordinates'][0]  # First ring
        elif polygon_geometry.get('type') == 'Feature':
            coordinates = polygon_geometry['geometry']['coordinates'][0]
        else:
            return 'global'
        
        # Calculate bounding box
        lons = [coord[0] for coord in coordinates]
        lats = [coord[1] for coord in coordinates]
        
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        
        # Portugal bounds
        portugal_bounds = {
            'west': -9.53, 'east': -6.19,
            'south': 36.96, 'north': 42.15,
        }
        
        # US bounds
        us_bounds = {
            'west': -125.0, 'east': -66.9,
            'south': 24.5, 'north': 49.0,
        }
        
        # Check if polygon is mostly within Portugal
        if (min_lon >= portugal_bounds['west'] and max_lon <= portugal_bounds['east'] and
            min_lat >= portugal_bounds['south'] and max_lat <= portugal_bounds['north']):
            return 'portugal'
        
        # Check if polygon is mostly within US
        if (min_lon >= us_bounds['west'] and max_lon <= us_bounds['east'] and
            min_lat >= us_bounds['south'] and max_lat <= us_bounds['north']):
            return 'us'
        
        return 'global'
        
    except Exception as e:
        print(f"Error detecting geographic region: {e}")
        return 'global'

@availability_bp.route('/lidar/check-availability', methods=['POST'])
def check_lidar_availability():
    """
    Check if LiDAR data is available for the given polygon
    """
    try:
        data = request.get_json()
        polygon = data.get('polygon')
        polygon_id = data.get('polygon_id')
        
        if not polygon:
            return jsonify({'error': 'Polygon geometry is required'}), 400
        
        # Detect geographic region
        region = detect_geographic_region(polygon)
        
        # LiDAR is only available in Portugal
        available = region == 'portugal'
        
        return jsonify({
            'available': available,
            'region': region,
            'message': f'LiDAR {"available" if available else "not available"} for {region} region'
        })
        
    except Exception as e:
        print(f"Error checking LiDAR availability: {e}")
        return jsonify({'error': 'Failed to check LiDAR availability'}), 500

@availability_bp.route('/usgs-dem/check-availability', methods=['POST'])
def check_usgs_dem_availability():
    """
    Check if USGS DEM data is available for the given polygon
    """
    try:
        data = request.get_json()
        polygon = data.get('polygon')
        polygon_id = data.get('polygon_id')
        
        if not polygon:
            return jsonify({'error': 'Polygon geometry is required'}), 400
        
        # Detect geographic region
        region = detect_geographic_region(polygon)
        
        # USGS DEM is only available in US
        available = region == 'us'
        
        return jsonify({
            'available': available,
            'region': region,
            'message': f'USGS DEM {"available" if available else "not available"} for {region} region'
        })
        
    except Exception as e:
        print(f"Error checking USGS DEM availability: {e}")
        return jsonify({'error': 'Failed to check USGS DEM availability'}), 500

@availability_bp.route('/srtm-high-res/check-availability', methods=['POST'])
def check_srtm_high_res_availability():
    """
    Check if SRTM High-Res data is available for the given polygon
    """
    try:
        data = request.get_json()
        polygon = data.get('polygon')
        polygon_id = data.get('polygon_id')
        
        if not polygon:
            return jsonify({'error': 'Polygon geometry is required'}), 400
        
        # Detect geographic region
        region = detect_geographic_region(polygon)
        
        # SRTM High-Res is available globally (for now)
        # You can add more sophisticated checks here later
        available = True
        
        return jsonify({
            'available': available,
            'region': region,
            'message': f'SRTM High-Res available globally'
        })
        
    except Exception as e:
        print(f"Error checking SRTM High-Res availability: {e}")
        return jsonify({'error': 'Failed to check SRTM High-Res availability'}), 500

# Register the blueprint in your main app
# In your main app.py or __init__.py:
# from routes.availability import availability_bp
# app.register_blueprint(availability_bp)
