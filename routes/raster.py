"""
Routes for serving raster files
"""
import os
import logging
from flask import request, jsonify, send_file, abort
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

def register_routes(app):
    """
    Register all raster-related routes
    
    Args:
        app: Flask application instance
    """
    
    @app.route('/raster/<path:file_path>', methods=['GET'])
    def serve_raster(file_path):
        """Serve raster files from the data directory"""
        try:
            # Security: Ensure the path is within the allowed directory
            if not file_path or '..' in file_path or file_path.startswith('/'):
                logger.warning(f"Invalid file path requested: {file_path}")
                abort(400)
            
            # Construct the full file path
            full_path = os.path.join('/app/data', file_path)
            
            # Security: Ensure the file is within the allowed directory
            if not os.path.abspath(full_path).startswith('/app/data'):
                logger.warning(f"Path traversal attempt: {file_path}")
                abort(403)
            
            # Check if file exists
            if not os.path.exists(full_path):
                logger.warning(f"File not found: {full_path}")
                abort(404)
            
            # Get file extension to determine content type
            file_ext = os.path.splitext(full_path)[1].lower()
            content_type_map = {
                '.tif': 'image/tiff',
                '.tiff': 'image/tiff',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.geojson': 'application/geo+json',
                '.json': 'application/json'
            }
            
            content_type = content_type_map.get(file_ext, 'application/octet-stream')
            
            logger.info(f"Serving raster file: {full_path}")
            return send_file(full_path, mimetype=content_type)
            
        except Exception as e:
            logger.error(f"Error serving raster file {file_path}: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': f'Failed to serve raster file: {str(e)}'
            }), 500
    
    @app.route('/api/raster', methods=['GET'])
    def serve_raster_api():
        """Serve raster files via API endpoint with path parameter"""
        try:
            file_path = request.args.get('path')
            if not file_path:
                return jsonify({
                    'status': 'error',
                    'message': 'path parameter is required'
                }), 400
            
            # Security: Ensure the path is within the allowed directory
            if '..' in file_path or file_path.startswith('/'):
                logger.warning(f"Invalid file path requested: {file_path}")
                return jsonify({
                    'status': 'error',
                    'message': 'Invalid file path'
                }), 400
            
            # Construct the full file path
            full_path = os.path.join('/app/data', file_path)
            
            # Security: Ensure the file is within the allowed directory
            if not os.path.abspath(full_path).startswith('/app/data'):
                logger.warning(f"Path traversal attempt: {file_path}")
                return jsonify({
                    'status': 'error',
                    'message': 'Access denied'
                }), 403
            
            # Check if file exists
            if not os.path.exists(full_path):
                logger.warning(f"File not found: {full_path}")
                return jsonify({
                    'status': 'error',
                    'message': 'File not found'
                }), 404
            
            # Get file extension to determine content type
            file_ext = os.path.splitext(full_path)[1].lower()
            content_type_map = {
                '.tif': 'image/tiff',
                '.tiff': 'image/tiff',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.geojson': 'application/geo+json',
                '.json': 'application/json'
            }
            
            content_type = content_type_map.get(file_ext, 'application/octet-stream')
            
            logger.info(f"Serving raster file via API: {full_path}")
            return send_file(full_path, mimetype=content_type)
            
        except Exception as e:
            logger.error(f"Error serving raster file via API: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': f'Failed to serve raster file: {str(e)}'
            }), 500
