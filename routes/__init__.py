"""
Route handlers for the Earthbenders application
"""
from routes import core, polygon, terrain, projects, raster, lidar

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
    projects.register_routes(app)
    raster.register_routes(app)
    lidar.register_routes(app)
    
    # Log registration
    import logging
    logger = logging.getLogger(__name__)
    logger.info("All routes registered successfully") 