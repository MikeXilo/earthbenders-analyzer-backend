"""
Core routes for the application (health check, static files)
"""
import logging
import time
import os
from flask import jsonify, send_from_directory

logger = logging.getLogger(__name__)

def register_routes(app):
    """
    Register core application routes
    
    Args:
        app: Flask application instance
    """
    @app.route('/')
    def index():
        return send_from_directory('.', 'index.html')

    @app.route('/<path:path>')
    def serve_file(path):
        return send_from_directory('.', path)
        
    @app.route('/health')
    def health_check():
        cors_origin = os.environ.get('CORS_ORIGIN', '*')
        return jsonify({
            'status': 'healthy',
            'timestamp': time.time(),
            'cors_origin': cors_origin
        }), 200 