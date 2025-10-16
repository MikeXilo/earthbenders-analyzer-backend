"""
LIDAR Analysis Routes

Handles LIDAR DEM processing with proper database integration
"""
import logging
from flask import Blueprint, request, jsonify
from services.lidar_processor import process_lidar_dem
from services.database import DatabaseService

logger = logging.getLogger(__name__)
db_service = DatabaseService()

# Create blueprint
lidar_analysis_bp = Blueprint('lidar_analysis', __name__)

def register_routes(app):
    """Register LIDAR analysis routes with Flask app"""
    app.register_blueprint(lidar_analysis_bp)

@lidar_analysis_bp.route('/api/lidar/process', methods=['POST'])
def process_lidar_analysis():
    """
    Process LIDAR DEM analysis with CRS transformation and database storage
    
    Expected request body:
    {
        "polygon": GeoJSON geometry,
        "polygon_id": "unique_id",
        "user_id": "user_id"
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
        polygon_id = data.get('polygon_id')
        user_id = data.get('user_id')
        
        if not polygon_id:
            return jsonify({
                'status': 'error',
                'message': 'Polygon ID required'
            }), 400
        
        logger.info(f"Processing LIDAR analysis for polygon {polygon_id}")
        
        # Process LIDAR DEM with CRS transformation
        lidar_results = process_lidar_dem(polygon_geometry, polygon_id)
        
        if 'error' in lidar_results:
            return jsonify({
                'status': 'error',
                'message': lidar_results['error']
            }), 500
        
        # Save results to database
        analysis_data = {
            'final_dem_path': lidar_results.get('final_dem_path'),
            'data_source': 'lidar',
            'statistics': lidar_results.get('statistics'),
            'bounds': lidar_results.get('bounds'),
            'image': lidar_results.get('image'),
            'status': lidar_results.get('status')
        }
        
        # Save to database
        db_result = db_service.save_analysis_results(polygon_id, analysis_data, user_id)
        
        if db_result.get('status') == 'error':
            logger.error(f"Database error saving LIDAR analysis: {db_result.get('message')}")
            return jsonify({
                'status': 'error',
                'message': f"Database error: {db_result.get('message')}"
            }), 500
        
        logger.info(f"LIDAR analysis completed and saved for polygon {polygon_id}")
        
        return jsonify({
            'status': 'success',
            'message': 'LIDAR analysis completed successfully',
            'results': {
                'final_dem_path': lidar_results.get('final_dem_path'),
                'bounds': lidar_results.get('bounds'),
                'statistics': lidar_results.get('statistics'),
                'data_source': 'lidar'
            }
        })
        
    except Exception as e:
        logger.error(f"Error processing LIDAR analysis: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Error: {str(e)}'
        }), 500
