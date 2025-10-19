"""
Water Harvesting API Routes
Provides endpoints for water harvesting potential calculations
"""
from flask import Blueprint, request, jsonify
import logging
from services.water_harvesting import WaterHarvestingService

logger = logging.getLogger(__name__)

# Create blueprint
water_harvesting_bp = Blueprint('water_harvesting', __name__)

# Initialize service
water_service = WaterHarvestingService()

@water_harvesting_bp.route('/api/water-harvesting/calculate', methods=['POST'])
def calculate_water_harvesting():
    """
    Calculate water harvesting potential for a polygon
    
    Expected JSON payload:
    {
        "polygon_geometry": {
            "type": "Polygon",
            "coordinates": [[[lon, lat], ...]]
        }
    }
    
    Returns:
    {
        "status": "success",
        "water_harvesting": {
            "area_hectares": 5.2,
            "annual_rainfall_mm": 600,
            "annual_harvest_liters": 21840000,
            "annual_harvest_gallons": 5770000,
            "comparisons": {...},
            "recommendations": {...},
            "cost_analysis": {...}
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        polygon_geometry = data.get('polygon_geometry')
        if not polygon_geometry:
            return jsonify({'error': 'polygon_geometry is required'}), 400
        
        # Validate polygon structure
        if not isinstance(polygon_geometry, dict) or polygon_geometry.get('type') != 'Polygon':
            return jsonify({'error': 'Invalid polygon geometry format'}), 400
        
        coordinates = polygon_geometry.get('coordinates')
        if not coordinates or not isinstance(coordinates, list) or len(coordinates) == 0:
            return jsonify({'error': 'Invalid polygon coordinates'}), 400
        
        logger.info(f"Calculating water harvesting potential for polygon")
        
        # Calculate water harvesting potential
        water_analysis = water_service.calculate_water_harvesting_potential(polygon_geometry)
        
        return jsonify({
            'status': 'success',
            'water_harvesting': water_analysis
        }), 200
        
    except Exception as e:
        logger.error(f"Error in water harvesting calculation: {str(e)}")
        return jsonify({
            'error': f'Water harvesting calculation failed: {str(e)}'
        }), 500

@water_harvesting_bp.route('/api/water-harvesting/health', methods=['GET'])
def health_check():
    """Health check endpoint for water harvesting service"""
    return jsonify({
        'status': 'healthy',
        'service': 'water_harvesting',
        'version': '1.0.0'
    }), 200

