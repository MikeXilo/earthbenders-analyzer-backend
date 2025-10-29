"""
Water Harvesting API Routes
Provides endpoints for water harvesting potential calculations
"""
from flask import Blueprint, request, jsonify
import logging
from services.water_harvesting import WaterHarvestingService
from utils.cors import jsonify_with_cors

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
        "average_slope_percent": 12.5,  // OPTIONAL - will use existing terrain analysis if available
        "user_id": "optional_user_identifier"
    }
    
    Smart Slope Detection:
    - If average_slope_percent is provided: Uses the provided value
    - If average_slope_percent is omitted: Automatically uses slope_mean from existing terrain analysis
    - If no terrain analysis exists: Returns helpful error message
    
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
            return jsonify_with_cors({'error': 'No JSON data provided'}), 400
        
        # Validate required fields
        polygon_geometry = data.get('polygon_geometry')
        if not polygon_geometry:
            return jsonify_with_cors({'error': 'polygon_geometry is required'}), 400
        
        polygon_id = data.get('polygon_id')
        if not polygon_id:
            return jsonify_with_cors({'error': 'polygon_id is required'}), 400
        
        # Smart slope detection: Use existing data or require manual input
        average_slope_percent = data.get('average_slope_percent')
        slope_source = 'manual'
        
        if average_slope_percent is None:
            logger.info(f"No slope provided, checking existing terrain analysis for {polygon_id}")
            
            from services.database import DatabaseService
            db = DatabaseService()
            analysis_data = db.get_analysis_record(polygon_id)
            
            if analysis_data:
                statistics = analysis_data.get('statistics')
                
                if statistics:
                    # Handle both string and dict formats
                    if isinstance(statistics, str):
                        import json
                        statistics = json.loads(statistics)
                    
                    # ✅ CORRECT: Access slope_mean directly from statistics
                    existing_slope = statistics.get('slope_mean')
                    
                    if existing_slope is not None and existing_slope > 0:
                        average_slope_percent = existing_slope
                        slope_source = 'terrain_analysis'
                        logger.info(f"✅ Using existing slope from terrain analysis: {average_slope_percent}%")
                        logger.info(f"   Slope stats: min={statistics.get('slope_min')}%, max={statistics.get('slope_max')}%, std={statistics.get('slope_std')}%")
                    else:
                        logger.warning(f"⚠️ Slope data exists but is invalid: slope_mean={existing_slope}")
                else:
                    logger.warning(f"⚠️ No statistics found in analysis for {polygon_id}")
            else:
                logger.warning(f"⚠️ No analysis record found for {polygon_id}")
        
        # If still no slope data, return helpful error
        if average_slope_percent is None:
            return jsonify_with_cors({
                'error': 'average_slope_percent is required',
                'message': 'No slope data available. Please either:\n1. Run slope analysis first (recommended): POST /process_slopes\n2. Provide average_slope_percent manually in the request',
                'help': {
                    'recommended': 'Run terrain analysis to calculate slopes automatically',
                    'quick': 'Provide "average_slope_percent" in request body (0-100)',
                    'example': {
                        "polygon_geometry": {"type": "Polygon", "coordinates": [[[...]]]},
                        "polygon_id": polygon_id,
                        "average_slope_percent": 15.5
                    }
                }
            }), 400
        
        # Optional fields
        user_id = data.get('user_id')
        
        # Validate polygon structure
        if not isinstance(polygon_geometry, dict) or polygon_geometry.get('type') != 'Polygon':
            return jsonify_with_cors({'error': 'Invalid polygon geometry format'}), 400
        
        coordinates = polygon_geometry.get('coordinates')
        if not coordinates or not isinstance(coordinates, list) or len(coordinates) == 0:
            return jsonify_with_cors({'error': 'Invalid polygon coordinates'}), 400
        
        # Validate slope
        try:
            slope = float(average_slope_percent)
            if slope < 0 or slope > 100:
                return jsonify_with_cors({'error': 'average_slope_percent must be between 0 and 100'}), 400
        except (ValueError, TypeError):
            return jsonify_with_cors({'error': 'average_slope_percent must be a number'}), 400
        
        logger.info(f"🌊 Calculating water harvesting for polygon {polygon_id}")
        logger.info(f"   Slope: {slope}% (source: {slope_source})")
        
        # ⚠️ Steep slope warnings
        slope_warnings = []
        if slope > 30:
            slope_warnings.append({
                'type': 'steep_slope_warning',
                'message': f'Very steep slope detected ({slope}%) - high erosion risk',
                'recommendations': [
                    'Consider terracing or swales to slow water flow',
                    'Implement vegetation for slope stabilization',
                    'Use downslope storage systems',
                    'Monitor for erosion after heavy rainfall'
                ]
            })
        elif slope > 15:
            slope_warnings.append({
                'type': 'moderate_slope_info',
                'message': f'Moderate slope ({slope}%) - good for water harvesting',
                'recommendations': [
                    'Consider contour swales for water capture',
                    'Plant vegetation to reduce runoff',
                    'Use berms to direct water flow'
                ]
            })
        
        # Calculate water harvesting potential and save to database
        water_analysis = water_service.calculate_water_harvesting_potential(
            polygon_geometry=polygon_geometry,
            polygon_id=polygon_id,
            average_slope_percent=slope,
            user_id=user_id
        )
        
        # Add metadata to response
        water_analysis['_metadata'] = {
            'slope_source': slope_source,
            'calculation_date': water_analysis.get('processed_at'),
            'data_quality': {
                'slope_data': 'from_terrain_analysis' if slope_source == 'terrain_analysis' else 'manual_input',
                'rainfall_data': 'real_api_data',
                'soil_data': 'real_api_data'
            },
            'slope_analysis': {
                'slope_percent': slope,
                'slope_category': 'very_steep' if slope > 30 else 'moderate' if slope > 15 else 'gentle',
                'runoff_characteristics': 'high_runoff' if slope > 30 else 'moderate_runoff' if slope > 15 else 'low_runoff'
            }
        }
        
        # Add warnings if any
        if slope_warnings:
            water_analysis['_warnings'] = slope_warnings
        
        return jsonify_with_cors({
            'status': 'success',
            'water_harvesting': water_analysis,
            'message': f'Water harvesting calculated successfully using {slope_source} slope data'
        }), 200
        
    except Exception as e:
        logger.error(f"Error in water harvesting calculation: {str(e)}", exc_info=True)
        return jsonify_with_cors({
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
            return jsonify_with_cors({
                'status': 'error',
                'message': f'No analysis found for polygon {polygon_id}'
            }), 404
        
        # Extract water harvesting data from statistics
        statistics = analysis_data.get('statistics', {})
        water_harvesting = statistics.get('water_harvesting')
        
        if not water_harvesting:
            return jsonify_with_cors({
                'status': 'error',
                'message': f'No water harvesting data found for polygon {polygon_id}'
            }), 404
        
        return jsonify_with_cors({
            'status': 'success',
            'water_harvesting': water_harvesting
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving water harvesting data: {str(e)}", exc_info=True)
        return jsonify_with_cors({
            'status': 'error',
            'message': f'Failed to retrieve water harvesting data: {str(e)}'
        }), 500

@water_harvesting_bp.route('/api/water-harvesting/health', methods=['GET'])
def health_check():
    """Health check endpoint for water harvesting service"""
    return jsonify_with_cors({
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