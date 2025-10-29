"""
Routes for analysis management and retrieval
"""
import logging
from flask import request, jsonify
from services.database import DatabaseService
from utils.cors import jsonify_with_cors

logger = logging.getLogger(__name__)

# Initialize database service
db_service = DatabaseService()

def register_routes(app):
    """
    Register all analysis-related routes
    
    Args:
        app: Flask application instance
    """
    
    @app.route('/api/analyses', methods=['POST'])
    def get_analysis_record():
        """
        Handles POST requests from the frontend to retrieve a specific analysis record by ID.
        (Frontend uses POST body to pass ID for security/convenience)
        """
        try:
            data = request.json
            # Check for polygon_id or analysis_id in the request body
            identifier = data.get('polygon_id') or data.get('analysis_id')

            if not identifier:
                return jsonify_with_cors({'error': 'Missing required polygon_id or analysis_id in request body.'}), 400
            
            # Retrieve the analysis record
            analysis_record = db_service.get_analysis_record(identifier)
            
            if analysis_record:
                return jsonify_with_cors(analysis_record), 200
            else:
                # If no analysis record, check polygon status
                polygon_metadata = db_service.get_polygon_metadata(identifier)
                if polygon_metadata and polygon_metadata.get('status') in ['submitted', 'processing']:
                     return jsonify_with_cors({'status': 'processing', 'message': 'Analysis is still in progress.'}), 202
                
                return jsonify_with_cors({'error': f'Analysis or polygon not found for ID: {identifier}'}), 404

        except Exception as e:
            logger.error(f"Error accessing /api/analyses: {str(e)}", exc_info=True)
            return jsonify_with_cors({'error': 'Internal server error during analysis retrieval'}), 500
