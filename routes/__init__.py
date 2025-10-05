"""
Route handlers for the Earthbenders application
"""
from routes import core, polygon, terrain

def register_all_routes(app):
    """
    Register all application routes with the Flask app
    
    Args:
        app: Flask application instance
    """
    # Register routes from each module
    core.register_routes(app)
    polygon.register_routes(app)
    terrain.register_routes(app)
    
    # Log registration
    import logging
    logger = logging.getLogger(__name__)
    logger.info("All routes registered successfully") 