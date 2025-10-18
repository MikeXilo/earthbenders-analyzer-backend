"""
Helper to find DEM files across all naming conventions
Supports: SRTM, LIDAR PT, LIDAR USA, legacy formats
"""
import os
import logging

logger = logging.getLogger(__name__)

def find_dem_file(polygon_session_folder: str, polygon_id: str) -> str:
    """
    Find DEM file using multiple naming patterns
    Supports: SRTM, LIDAR PT, LIDAR USA, legacy formats
    
    Search order:
    1. clipped_dem.tif (unified, all sources)
    2. {polygon_id}_srtm.tif (legacy SRTM)
    3. clipped_srtm.tif (legacy LIDAR)
    4. {polygon_id}_dem.tif (alternative naming)
    
    Args:
        polygon_session_folder: Path to polygon session folder
        polygon_id: Polygon identifier
        
    Returns:
        str: Path to DEM file, or None if not found
    """
    search_patterns = [
        ("clipped_dem.tif", "Unified DEM (all sources)"),
        (f"{polygon_id}_srtm.tif", "Legacy SRTM naming"),
        ("clipped_srtm.tif", "Legacy LIDAR naming"),
        (f"{polygon_id}_dem.tif", "Alternative naming")
    ]
    
    for filename, description in search_patterns:
        file_path = os.path.join(polygon_session_folder, filename)
        if os.path.exists(file_path):
            logger.info(f"✅ Found DEM file ({description}): {file_path}")
            return file_path
    
    logger.error(f"❌ No DEM file found in {polygon_session_folder}")
    logger.error(f"   Searched patterns: {[p[0] for p in search_patterns]}")
    return None

def get_dem_file_info(file_path: str) -> dict:
    """
    Get information about a DEM file
    
    Args:
        file_path: Path to DEM file
        
    Returns:
        dict: File information including size, modification time, etc.
    """
    if not file_path or not os.path.exists(file_path):
        return None
        
    stat = os.stat(file_path)
    return {
        'path': file_path,
        'size_bytes': stat.st_size,
        'size_mb': round(stat.st_size / (1024 * 1024), 2),
        'modified_time': stat.st_mtime,
        'exists': True
    }
