"""
Routes for serving raster files
"""
import os
import logging
import time
import requests
from flask import request, jsonify, send_file, abort, Response
from utils.cors import jsonify_with_cors, add_cors_headers
from werkzeug.utils import secure_filename
from services.raster_visualization import process_raster_file, detect_layer_type_from_path
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import threading
from collections import deque

logger = logging.getLogger(__name__)

# WMS proxy connection pool and throttling
_wms_session_lock = threading.Lock()
_wms_session = None
_wms_request_queue = deque()
_wms_max_concurrent = 2  # Limit concurrent WMS requests (reduced to avoid rate limiting)
_wms_active_requests = 0
_wms_queue_lock = threading.Lock()

def get_wms_session():
    """Get or create a shared WMS session with connection pooling"""
    global _wms_session
    with _wms_session_lock:
        if _wms_session is None:
            _wms_session = requests.Session()
            
            # Configure retry strategy
            retry_strategy = Retry(
                total=2,  # Total retries
                backoff_factor=1.0,  # Wait 1s, 2s between retries
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["GET"],
                raise_on_status=False
            )
            
            # Configure adapter with connection pooling
            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=2,  # Number of connection pools
                pool_maxsize=5,  # Max connections per pool
                pool_block=False  # Don't block when pool is full
            )
            
            _wms_session.mount("https://", adapter)
            _wms_session.mount("http://", adapter)
            
            # Set headers
            _wms_session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/png,image/*,*/*;q=0.8',
                'Accept-Language': 'pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Cache-Control': 'no-cache',
            })
    return _wms_session

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

    @app.route('/api/wms-proxy', methods=['OPTIONS'])
    def wms_proxy_options():
        """Handle CORS preflight requests for WMS proxy"""
        return jsonify_with_cors({}), 200

    @app.route('/api/wms-proxy', methods=['GET'])
    def wms_proxy():
        """
        Proxy WMS GetMap requests to bypass CORS restrictions
        This endpoint forwards WMS requests from the frontend to the WMS service
        with connection pooling and throttling to avoid rate limiting
        """
        global _wms_active_requests
        
        try:
            # Get WMS parameters from query string
            service = request.args.get('service', 'WMS')
            version = request.args.get('version', '1.3.0')
            request_type = request.args.get('request', 'GetMap')
            layers = request.args.get('layers')
            bbox = request.args.get('bbox')
            width = request.args.get('width', '256')
            height = request.args.get('height', '256')
            format_type = request.args.get('format', 'image/png')
            crs = request.args.get('crs', 'EPSG:3857')
            transparent = request.args.get('transparent', 'true')
            styles = request.args.get('styles', '')
            
            # Get the WMS base URL from query parameter or use default
            # Correct URL from GetCapabilities: https://geo2.dgterritorio.gov.pt/wms/COSc_preverao
            wms_base_url = request.args.get('wms_url', 'https://geo2.dgterritorio.gov.pt/wms/COSc_preverao')
            
            # Validate required parameters
            if not layers or not bbox:
                return jsonify_with_cors({
                    'status': 'error',
                    'message': 'Missing required parameters: layers and bbox are required'
                }), 400
            
            # Construct WMS GetMap URL
            # Use proper URL encoding and handle WMS 1.1.1 vs 1.3.0 differences
            from urllib.parse import urlencode
            
            # WMS 1.1.1 uses SRS, WMS 1.3.0 uses CRS
            # For WMS 1.1.1, SRS should be in format "EPSG:XXXX" (most common) or just "EPSGXXXX"
            if version == '1.1.1':
                # Keep the full CRS format (EPSG:3857) for SRS in WMS 1.1.1
                # Some services accept both "EPSG:3857" and "3857", but "EPSG:3857" is more standard
                srs_param = crs if crs.startswith('EPSG:') else f'EPSG:{crs}' if not ':' in str(crs) else crs
                wms_params = {
                    'service': service,
                    'version': version,
                    'request': request_type,
                    'layers': layers,
                    'bbox': bbox,
                    'width': width,
                    'height': height,
                    'format': format_type,
                    'srs': srs_param,
                    'transparent': transparent,
                    # STYLES is REQUIRED for WMS 1.1.1 (even if empty string)
                    'styles': styles if styles else '',  # Always include, empty string if not provided
                }
            else:
                # WMS 1.3.0
                wms_params = {
                    'service': service,
                    'version': version,
                    'request': request_type,
                    'layers': layers,
                    'bbox': bbox,
                    'width': width,
                    'height': height,
                    'format': format_type,
                    'crs': crs,
                    'transparent': transparent,
                }
                # For WMS 1.3.0, styles is optional but we include it if provided
                if styles:
                    wms_params['styles'] = styles
            
            # Build URL with proper encoding
            wms_url = f"{wms_base_url}?{urlencode(wms_params)}"
            
            # Throttle requests to avoid overwhelming the WMS service
            # Add a small delay between requests to avoid rate limiting
            with _wms_queue_lock:
                # Wait if we have too many concurrent requests
                wait_attempts = 0
                max_wait_attempts = 50  # Wait up to 5 seconds (50 * 0.1s)
                while _wms_active_requests >= _wms_max_concurrent and wait_attempts < max_wait_attempts:
                    _wms_queue_lock.release()
                    time.sleep(0.1)  # Wait 100ms
                    wait_attempts += 1
                    _wms_queue_lock.acquire()
                
                if _wms_active_requests >= _wms_max_concurrent:
                    logger.warning(f"WMS request queue full, rejecting request for {bbox}")
                    return jsonify_with_cors({
                        'status': 'error',
                        'message': 'WMS service is busy, please try again in a moment'
                    }), 503
                
                _wms_active_requests += 1
                
                # Add small delay between requests (50ms) to avoid rate limiting
                # This mimics more human-like request patterns
                if _wms_active_requests > 1:
                    time.sleep(0.05)
            
            try:
                logger.info(f"Proxying WMS request (version {version}): {wms_url[:300]}...")
                
                # Get shared session with connection pooling
                session = get_wms_session()
                
                # Make request with timeout and streaming
                # Use a shorter timeout to fail fast if service is down
                response = session.get(
                    wms_url,
                    timeout=(10, 30),  # 10s connect, 30s read timeout
                    stream=True,
                    allow_redirects=True
                )
                
                # Check response status
                if response.status_code != 200:
                    error_text = response.text[:200] if hasattr(response, 'text') else ''
                    logger.warning(f"WMS service returned {response.status_code}: {error_text}")
                    return jsonify_with_cors({
                        'status': 'error',
                        'message': f'WMS service returned error: {response.status_code}'
                    }), response.status_code
                
                # Read response content
                content = response.content
                content_type = response.headers.get('Content-Type', '')
                
                # Log response details for debugging
                logger.info(f"WMS response: {len(content)} bytes, Content-Type: {content_type}")
                
                # Check if response is XML error instead of image
                # WMS errors are typically XML even with 200 status code
                if content_type and ('xml' in content_type.lower() or 'html' in content_type.lower()):
                    error_text = content.decode('utf-8', errors='ignore')[:500]
                    logger.error(f"WMS returned XML/HTML instead of image (Content-Type: {content_type}): {error_text}")
                    return jsonify_with_cors({
                        'status': 'error',
                        'message': 'WMS service returned an error response (XML instead of image)'
                    }), 500
                
                # Check if content looks like XML/HTML (common WMS error response)
                if content.startswith(b'<?xml') or content.startswith(b'<html') or content.startswith(b'<ServiceException'):
                    error_text = content.decode('utf-8', errors='ignore')[:500]
                    logger.error(f"WMS returned XML/HTML error response: {error_text}")
                    return jsonify_with_cors({
                        'status': 'error',
                        'message': 'WMS service returned an error response'
                    }), 500
                
                # Verify it's actually an image (PNG signature: 89 50 4E 47)
                # Check for PNG signature more flexibly (some PNGs may have slight variations)
                is_png = (len(content) >= 8 and 
                         content[0] == 0x89 and 
                         content[1:4] == b'PNG' and
                         content[4:7] == b'\r\n\x1a\n')
                
                # Check if it's XML/HTML error (WMS typically returns XML errors)
                is_xml_error = (content.startswith(b'<?xml') or 
                               content.startswith(b'<html') or 
                               content.startswith(b'<ServiceException') or
                               b'ServiceException' in content[:200] or
                               (content_type and ('xml' in content_type.lower() or 'html' in content_type.lower())))
                
                if is_xml_error:
                    # Definitely an error - decode and log
                    try:
                        error_text = content.decode('utf-8', errors='ignore')[:500]
                        logger.error(f"WMS returned XML/HTML error (Content-Type: {content_type}): {error_text}")
                        return jsonify_with_cors({
                            'status': 'error',
                            'message': 'WMS service returned an error response'
                        }), 500
                    except:
                        logger.error(f"WMS returned XML/HTML error (could not decode): {content[:200]}")
                        return jsonify_with_cors({
                            'status': 'error',
                            'message': 'WMS service returned an error response'
                        }), 500
                
                # If not PNG and very small, might be an error
                if not is_png and len(content) < 500:
                    logger.warning(f"WMS returned suspiciously small non-PNG response: {len(content)} bytes, starts with: {content[:50].hex()}")
                    # Try to decode as text to see if it's an error message
                    try:
                        error_text = content.decode('utf-8', errors='ignore')[:500]
                        if 'error' in error_text.lower() or 'exception' in error_text.lower():
                            logger.error(f"WMS error in small response: {error_text}")
                            return jsonify_with_cors({
                                'status': 'error',
                                'message': 'WMS service returned an error'
                            }), 500
                    except:
                        pass
                    
                    # If it's very small and not PNG, reject it
                    if len(content) < 100:
                        logger.error(f"Response too small to be valid ({len(content)} bytes)")
                        return jsonify_with_cors({
                            'status': 'error',
                            'message': f'WMS returned invalid response ({len(content)} bytes, expected image)'
                        }), 500
                    # If between 100-500 bytes and not PNG, log warning but allow it
                    # (might be a valid small transparent PNG or single-color image)
                    logger.info(f"Small response ({len(content)} bytes) - not a standard PNG, but allowing it")
                
                # Create Flask response with image data
                flask_response = Response(
                    content,
                    mimetype=content_type,
                    status=200
                )
                
                # Add CORS headers
                flask_response = add_cors_headers(flask_response)
                
                # Add cache headers (cache WMS tiles for 1 hour)
                flask_response.headers['Cache-Control'] = 'public, max-age=3600'
                
                logger.debug(f"Successfully proxied WMS request, returning {len(content)} bytes")
                return flask_response
                
            finally:
                # Always decrement active request counter
                with _wms_queue_lock:
                    _wms_active_requests = max(0, _wms_active_requests - 1)
            
        except requests.exceptions.Timeout:
            logger.error("WMS request timed out")
            return jsonify_with_cors({
                'status': 'error',
                'message': 'WMS request timed out'
            }), 504
        except requests.exceptions.ConnectionError as e:
            logger.error(f"WMS connection error: {str(e)}")
            return jsonify_with_cors({
                'status': 'error',
                'message': 'WMS service connection failed. The service may be temporarily unavailable.'
            }), 503
        except requests.exceptions.RequestException as e:
            logger.error(f"Error proxying WMS request: {str(e)}")
            return jsonify_with_cors({
                'status': 'error',
                'message': f'Failed to proxy WMS request: {str(e)[:100]}'
            }), 500
        except Exception as e:
            logger.error(f"Unexpected error in WMS proxy: {str(e)}", exc_info=True)
            return jsonify_with_cors({
                'status': 'error',
                'message': f'Internal server error: {str(e)[:100]}'
            }), 500
        finally:
            # Ensure we always decrement the counter even on unexpected errors
            try:
                with _wms_queue_lock:
                    _wms_active_requests = max(0, _wms_active_requests - 1)
            except:
                pass