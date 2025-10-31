"""
Routes for serving raster files
"""
import os
import logging
from flask import request, jsonify, send_file, abort
from utils.cors import jsonify_with_cors
from werkzeug.utils import secure_filename
from services.raster_visualization import process_raster_file, detect_layer_type_from_path

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
            return jsonify_with_cors({
                'status': 'error',
                'message': f'Failed to serve raster file: {str(e)}'
            }), 500
    
    @app.route('/api/raster', methods=['GET'])
    def serve_raster_api():
        """Serve raster files via API endpoint with path parameter"""
        try:
            file_path = request.args.get('path')
            polygon_data = request.args.get('polygon')
            
            if not file_path:
                return jsonify_with_cors({
                    'status': 'error',
                    'message': 'path parameter is required'
                }), 400
            
            # Security: Ensure the path is within the allowed directory
            if '..' in file_path or file_path.startswith('/'):
                logger.warning(f"Invalid file path requested: {file_path}")
                return jsonify_with_cors({
                    'status': 'error',
                    'message': 'Invalid file path'
                }), 400
            
            # Construct the full file path
            full_path = os.path.join('/app/data', file_path)
            
            # Security: Ensure the file is within the allowed directory
            if not os.path.abspath(full_path).startswith('/app/data'):
                logger.warning(f"Path traversal attempt: {file_path}")
                return jsonify_with_cors({
                    'status': 'error',
                    'message': 'Access denied'
                }), 403
            
            # Check if file exists
            if not os.path.exists(full_path):
                logger.warning(f"File not found: {full_path}")
                return jsonify_with_cors({
                    'status': 'error',
                    'message': 'File not found'
                }), 404
            
            # Get file extension to determine content type
            file_ext = os.path.splitext(full_path)[1].lower()
            
            # Handle GeoTIFF files with visualization processing
            if file_ext in ['.tif', '.tiff']:
                # Detect layer type from file path
                layer_type = detect_layer_type_from_path(full_path)
                
                if layer_type:
                    logger.info(f"Processing GeoTIFF for {layer_type} visualization: {full_path}")
                    
                    try:
                        # Parse polygon data if provided
                        parsed_polygon_data = None
                        if polygon_data:
                            import json
                            try:
                                parsed_polygon_data = json.loads(polygon_data)
                                logger.info(f"Using polygon data for masking: {layer_type}")
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse polygon data: {e}")
                        
                        # Process the raster file and get Base64 PNG
                        base64_image_data = process_raster_file(full_path, layer_type, parsed_polygon_data)
                        
                        if base64_image_data is None:
                            # Handle special cases like contours (GeoJSON files)
                            if layer_type == 'contours':
                                logger.info(f"Contours are GeoJSON files, serving raw file: {full_path}")
                                return send_file(full_path, mimetype='application/geo+json')
                            else:
                                return jsonify_with_cors({
                                    'status': 'error',
                                    'message': f'Failed to process {layer_type} visualization'
                                }), 500
                        
                        # Return the Base64 data as a JSON object
                        # The frontend will now treat this like the working processSRTM result
                        return jsonify_with_cors({'image': base64_image_data}), 200
                        
                    except Exception as e:
                        logger.error(f"Error processing {layer_type} visualization: {str(e)}")
                        return jsonify_with_cors({
                            'status': 'error',
                            'message': f'Failed to process {layer_type} visualization: {str(e)}'
                        }), 500
                else:
                    logger.warning(f"Could not determine layer type from path: {full_path}")
                    # Fallback to serving raw file if type cannot be determined
                    logger.info(f"Falling back to serving raw GeoTIFF: {full_path}")
                    return send_file(full_path, mimetype='image/tiff')
            
            # Handle all non-GeoTIFF files (like existing PNGs, if any)
            content_type_map = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.geojson': 'application/geo+json',
                '.json': 'application/json'
            }
            
            content_type = content_type_map.get(file_ext, 'application/octet-stream')
            
            logger.info(f"Serving raw file via API: {full_path}")
            return send_file(full_path, mimetype=content_type)
            
        except Exception as e:
            logger.error(f"Error serving raster file via API: {str(e)}")
            return jsonify_with_cors({
                'status': 'error',
                'message': f'Failed to serve raster file: {str(e)}'
            }), 500

    @app.route('/visualize_raster', methods=['POST'])
    def visualize_raster():
        """Visualize a raster file and return base64 PNG image"""
        try:
            data = request.get_json()
            if not data:
                return jsonify_with_cors({'error': 'No JSON data provided'}), 400
            
            file_path = data.get('file_path')
            layer_type = data.get('layer_type')
            polygon_id = data.get('polygon_id')
            
            if not file_path or not layer_type:
                return jsonify_with_cors({'error': 'Missing required parameters: file_path and layer_type'}), 400
            
            logger.info(f"Visualizing raster: {file_path} (type: {layer_type})")
            
            # Construct the full file path (same logic as /raster/ endpoint)
            full_path = file_path
            if not file_path.startswith('/app/data/'):
                # If it's a relative path, construct the full path
                full_path = os.path.join('/app/data', file_path)
            
            # Check if file exists
            if not os.path.exists(full_path):
                logger.warning(f"File not found: {full_path}")
                return jsonify_with_cors({'error': f'File not found: {full_path}'}), 404
            
            # Get polygon data if polygon_id is provided
            polygon_data = None
            if polygon_id:
                try:
                    from services.database import DatabaseService
                    import json
                    db_service = DatabaseService()
                    
                    # Get polygon geometry from geojson file
                    conn = db_service._get_connection()
                    if conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT geojson_path FROM polygons WHERE id = %s
                        """, (polygon_id,))
                        
                        row = cursor.fetchone()
                        if row and row['geojson_path']:
                            geojson_file_path = os.path.join('/app/data', row['geojson_path'])
                            if os.path.exists(geojson_file_path):
                                with open(geojson_file_path, 'r') as f:
                                    polygon_data = json.load(f)
                                logger.info(f"Using polygon data for masking: {polygon_id}")
                            else:
                                logger.warning(f"GeoJSON file not found: {geojson_file_path}")
                        
                        cursor.close()
                        conn.close()
                except Exception as e:
                    logger.warning(f"Failed to get polygon data: {str(e)}")
            
            # Process the raster file
            base64_image_data = process_raster_file(full_path, layer_type, polygon_data)
            
            if base64_image_data is None:
                return jsonify_with_cors({'error': f'Failed to process {layer_type} visualization'}), 500
            
            logger.info(f"Successfully generated {layer_type} visualization")
            return jsonify_with_cors({
                'status': 'success',
                'image': base64_image_data,
                'layer_type': layer_type,
                'file_path': file_path
            })
            
        except Exception as e:
            logger.error(f"Error in visualize_raster: {str(e)}")
            return jsonify_with_cors({'error': f'Internal server error: {str(e)}'}), 500