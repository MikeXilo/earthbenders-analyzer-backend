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
        },
        "polygon_id": "unique_polygon_identifier",
        "average_slope_percent": 12.5,
        "user_id": "optional_user_identifier"
    }
    
    Returns:
    {
        "status": "success",
        "water_harvesting": {
            "area_hectares": 5.2,
            "climate": {
                "annual_rainfall_mm": 774
            },
            "terrain": {
                "average_slope_percent": 12.5,
                "soil_type": "clay_loam",
                "soil_details": {
                    "wrb_class": "Luvisols",
                    "data_source": "classification"
                }
            },
            "runoff_coefficient": 0.58,
            "harvest_potential": {
                "annual_liters": 2942920,
                ...
            },
            ...
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Validate required fields
        polygon_geometry = data.get('polygon_geometry')
        if not polygon_geometry:
            return jsonify({'error': 'polygon_geometry is required'}), 400
        
        polygon_id = data.get('polygon_id')
        if not polygon_id:
            return jsonify({'error': 'polygon_id is required'}), 400
        
        average_slope_percent = data.get('average_slope_percent')
        if average_slope_percent is None:
            return jsonify({'error': 'average_slope_percent is required (in percent, e.g., 12.5 for 12.5%)'}), 400
        
        # Optional fields
        user_id = data.get('user_id')
        
        # Validate polygon structure
        if not isinstance(polygon_geometry, dict) or polygon_geometry.get('type') != 'Polygon':
            return jsonify({'error': 'Invalid polygon geometry format'}), 400
        
        coordinates = polygon_geometry.get('coordinates')
        if not coordinates or not isinstance(coordinates, list) or len(coordinates) == 0:
            return jsonify({'error': 'Invalid polygon coordinates'}), 400
        
        # Validate slope
        try:
            slope = float(average_slope_percent)
            if slope < 0 or slope > 100:
                return jsonify({'error': 'average_slope_percent must be between 0 and 100'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'average_slope_percent must be a number'}), 400
        
        logger.info(f"Calculating water harvesting for polygon {polygon_id} with {slope}% slope")
        
        # Calculate water harvesting potential and save to database
        water_analysis = water_service.calculate_water_harvesting_potential(
            polygon_geometry=polygon_geometry,
            polygon_id=polygon_id,
            average_slope_percent=slope,
            user_id=user_id
        )
        
        return jsonify({
            'status': 'success',
            'water_harvesting': water_analysis
        }), 200
        
    except Exception as e:
        logger.error(f"Error in water harvesting calculation: {str(e)}", exc_info=True)
        return jsonify({
            'error': f'Water harvesting calculation failed: {str(e)}'
        }), 500

@water_harvesting_bp.route('/api/water-harvesting/<polygon_id>', methods=['GET'])
def get_water_harvesting(polygon_id):
    """
    Retrieve existing water harvesting data for a polygon
    
    Returns:
    {
        "status": "success",
        "water_harvesting": {
            "area_hectares": 5.2,
            "climate": {
                "annual_rainfall_mm": 774
            },
            ...
        }
    }
    """
    try:
        from services.database import DatabaseService
        
        db = DatabaseService()
        
        # Get analysis data for the polygon
        analysis_data = db.get_analysis_by_polygon_id(polygon_id)
        
        if not analysis_data:
            return jsonify({
                'status': 'error',
                'message': f'No analysis found for polygon {polygon_id}'
            }), 404
        
        # Extract water harvesting data from statistics
        statistics = analysis_data.get('statistics', {})
        water_harvesting = statistics.get('water_harvesting')
        
        if not water_harvesting:
            return jsonify({
                'status': 'error',
                'message': f'No water harvesting data found for polygon {polygon_id}'
            }), 404
        
        return jsonify({
            'status': 'success',
            'water_harvesting': water_harvesting
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving water harvesting data: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': f'Failed to retrieve water harvesting data: {str(e)}'
        }), 500

@water_harvesting_bp.route('/api/water-harvesting/health', methods=['GET'])
def health_check():
    """Health check endpoint for water harvesting service"""
    return jsonify({
        'status': 'healthy',
        'service': 'water_harvesting',
        'version': '2.0.0',
        'features': [
            'Real rainfall data (Open-Meteo + NASA POWER)',
            'Real soil data (SoilGrids properties + classification)',
            'WRB soil type mapping',
            'Slope-based runoff coefficient',
            'ROI calculations',
            'Storage recommendations'
        ]
    }), 200