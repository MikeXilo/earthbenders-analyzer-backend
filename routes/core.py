"""
Core routes for the application (health check, static files)
"""
import logging
import time
import os
from flask import jsonify, send_from_directory
from utils.cors import jsonify_with_cors

logger = logging.getLogger(__name__)

def register_routes(app):
    """
    Register core application routes
    
    Args:
        app: Flask application instance
    """
    @app.route('/')
    def index():
        # Return a simple health check JSON response for the root endpoint
        # instead of trying to serve a non-existent index.html file.
        return jsonify_with_cors({
            'status': 'API Running',
            'message': 'Welcome to the Earthbenders API. Use /health for full check.',
            'timestamp': time.time()
        }), 200

    @app.route('/<path:path>')
    def serve_file(path):
        # This is a fallback static file handler, but should ideally not be used
        # in a pure API. It remains here for completeness.
        return send_from_directory('.', path)
        
    @app.route('/health')
    def health_check():
        """Simple health check endpoint that doesn't depend on external services"""
        try:
            cors_origin = os.environ.get('CORS_ORIGIN', '*')
            return jsonify_with_cors({
                'status': 'healthy',
                'timestamp': time.time(),
                'cors_origin': cors_origin,
                'message': 'Backend service is running'
            }), 200
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return jsonify_with_cors({
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': time.time()
            }), 500
