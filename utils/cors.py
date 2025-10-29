"""
CORS utility functions to simplify adding CORS headers to Flask responses
"""
from flask import jsonify

def add_cors_headers(response):
    """
    Add CORS headers to a Flask response object.
    
    Args:
        response: Flask Response object from jsonify() or make_response()
    
    Returns:
        Response object with CORS headers added
    """
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, PATCH'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

def jsonify_with_cors(*args, **kwargs):
    """
    Create a JSON response with CORS headers already added.
    
    Usage:
        return jsonify_with_cors({'status': 'success', 'data': ...})
        return jsonify_with_cors({'error': 'Not found'}, 404)
    """
    response = jsonify(*args, **kwargs)
    return add_cors_headers(response)

