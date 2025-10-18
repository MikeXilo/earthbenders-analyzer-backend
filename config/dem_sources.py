"""
Configuration for different DEM data sources
"""

DEM_CONFIG = {
    'srtm': {
        'cache_dir': '/app/data/srtm/',
        'resolution': 30,  # meters
        'max_file_size': 100 * 1024 * 1024,  # 100MB
        'expected_crs': 'EPSG:4326',
        'description': 'Shuttle Radar Topography Mission - Global 30m resolution'
    },
    'lidar': {
        'cache_dir': '/app/data/LidarPt/',
        'resolution': 1,  # meters
        'max_file_size': 500 * 1024 * 1024,  # 500MB
        'expected_crs': 'EPSG:4326',  # After reprojection
        'source_crs': 'EPSG:3763',  # ETRS89/TM06 before reprojection
        'description': 'LiDAR Portugal - High resolution 1m data'
    },
    'usgs-dem': {
        'cache_dir': '/app/data/LidarUSA/',
        'resolution': 10,  # meters
        'max_file_size': 200 * 1024 * 1024,  # 200MB
        'expected_crs': 'EPSG:4326',  # Requested from ArcGIS API in WGS84
        'api_crs_handling': 'request_wgs84',  # API handles reprojection
        'description': 'USGS 3DEP DEM - High resolution 10m data (requested in WGS84)'
    }
}

def get_dem_config(data_source: str) -> dict:
    """Get configuration for a specific DEM data source"""
    if data_source not in DEM_CONFIG:
        raise ValueError(f"Unknown data source: {data_source}")
    return DEM_CONFIG[data_source]

def validate_dem_source(data_source: str) -> bool:
    """Validate if data source is supported"""
    return data_source in DEM_CONFIG

def get_all_supported_sources() -> list:
    """Get list of all supported data sources"""
    return list(DEM_CONFIG.keys())
