"""
Route handlers for the Earthbenders application
"""
from routes import core, polygon, terrain, projects, raster, lidar, analyses

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
    analyses.register_routes(app)
    # Register USGS DEM routes (Blueprint)
    try:
        from routes.usgs_dem import usgs_dem_bp
        app.register_blueprint(usgs_dem_bp)
        import logging
        logger = logging.getLogger(__name__)
        logger.info("USGS DEM routes registered successfully")
    except ImportError as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to import USGS DEM routes: {e}")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to register USGS DEM routes: {e}")
    
    # Register Water Harvesting routes (Blueprint)
    try:
        from routes.water_harvesting import water_harvesting_bp
        app.register_blueprint(water_harvesting_bp)
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Water Harvesting routes registered successfully")
    except ImportError as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to import Water Harvesting routes: {e}")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to register Water Harvesting routes: {e}")
    
    # Log registration
    import logging
    logger = logging.getLogger(__name__)
    logger.info("All routes registered successfully") 