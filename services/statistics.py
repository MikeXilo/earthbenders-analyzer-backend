"""
Statistics calculation service for terrain analysis
"""
import os
import logging
import numpy as np
import rasterio
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

def calculate_terrain_statistics(srtm_path: str, slope_path: str, aspect_path: str, bounds: Dict[str, float]) -> Dict[str, Any]:
    """
    Calculate terrain statistics from SRTM, slope, and aspect files
    
    Args:
        srtm_path: Path to SRTM elevation file
        slope_path: Path to slope file
        aspect_path: Path to aspect file
        bounds: Bounding box coordinates
        
    Returns:
        Dictionary with calculated statistics
    """
    try:
        logger.info(f"Calculating terrain statistics for files: {srtm_path}, {slope_path}, {aspect_path}")
        
        # Check if SRTM file exists (required)
        if not os.path.exists(srtm_path):
            logger.error(f"SRTM file not found: {srtm_path}")
            return {}
        
        # Check if slope and aspect files exist (optional)
        slope_exists = slope_path and os.path.exists(slope_path)
        aspect_exists = aspect_path and os.path.exists(aspect_path)
        
        # Read SRTM data
        with rasterio.open(srtm_path) as src:
            srtm_data = src.read(1)
            srtm_nodata = src.nodata
            
        # Read slope data if available
        slope_data = None
        slope_nodata = None
        if slope_exists:
            with rasterio.open(slope_path) as src:
                slope_data = src.read(1)
                slope_nodata = src.nodata
            
        # Read aspect data if available
        aspect_data = None
        aspect_nodata = None
        if aspect_exists:
            with rasterio.open(aspect_path) as src:
                aspect_data = src.read(1)
                aspect_nodata = src.nodata
        
        # Mask out nodata values
        srtm_masked = srtm_data[srtm_data != srtm_nodata] if srtm_nodata is not None else srtm_data
        slope_masked = slope_data[slope_data != slope_nodata] if slope_data is not None and slope_nodata is not None else (slope_data if slope_data is not None else np.array([]))
        aspect_masked = aspect_data[aspect_data != aspect_nodata] if aspect_data is not None and aspect_nodata is not None else (aspect_data if aspect_data is not None else np.array([]))
        
        # Calculate elevation statistics
        elevation_min = float(np.min(srtm_masked)) if len(srtm_masked) > 0 else 0
        elevation_max = float(np.max(srtm_masked)) if len(srtm_masked) > 0 else 0
        elevation_mean = float(np.mean(srtm_masked)) if len(srtm_masked) > 0 else 0
        
        # Calculate slope statistics (only if slope data exists)
        slope_mean = float(np.mean(slope_masked)) if len(slope_masked) > 0 and slope_exists else 0
        slope_min = float(np.min(slope_masked)) if len(slope_masked) > 0 and slope_exists else 0
        slope_max = float(np.max(slope_masked)) if len(slope_masked) > 0 and slope_exists else 0
        slope_std = float(np.std(slope_masked)) if len(slope_masked) > 0 and slope_exists else 0
        
        # Calculate aspect statistics (only if aspect data exists)
        aspect_mean = float(np.mean(aspect_masked)) if len(aspect_masked) > 0 and aspect_exists else 0
        
        # Determine aspect direction
        aspect_direction = get_aspect_direction(aspect_mean) if aspect_exists else "Unknown"
        
        # Calculate area (approximate from pixel count)
        # This is a rough estimate - for accurate area calculation, we'd need proper coordinate transformation
        pixel_count = len(srtm_masked)
        # Assuming 30m resolution (typical for SRTM)
        pixel_area_m2 = 30 * 30  # 900 m² per pixel
        area_km2 = (pixel_count * pixel_area_m2) / 1_000_000  # Convert to km²
        
        # Calculate terrain ruggedness (standard deviation of elevation)
        terrain_ruggedness = float(np.std(srtm_masked)) if len(srtm_masked) > 0 else 0
        
        # Calculate relief (elevation range)
        relief = elevation_max - elevation_min
        
        # Import datetime for processed_at
        from datetime import datetime
        
        statistics = {
            'bounds': bounds,
            'relief': round(relief, 2),
            'area_km2': round(area_km2, 4),
            'slope_max': round(slope_max, 2),
            'slope_min': round(slope_min, 2),
            'slope_std': round(slope_std, 2),
            'slope_mean': round(slope_mean, 2),
            'aspect_mean': round(aspect_mean, 2),
            'aspect_path': aspect_path,
            'pixel_count': pixel_count,
            'processed_at': datetime.now().isoformat(),
            'elevation_max': round(elevation_max, 2),
            'elevation_min': round(elevation_min, 2),
            'elevation_mean': round(elevation_mean, 2),
            'aspect_direction': aspect_direction,
            'terrain_ruggedness': round(terrain_ruggedness, 2)
        }
        
        logger.info(f"Calculated statistics: {statistics}")
        return statistics
        
    except Exception as e:
        logger.error(f"Error calculating terrain statistics: {str(e)}")
        return {}

def get_aspect_direction(aspect_degrees: float) -> str:
    """
    Convert aspect degrees to cardinal direction
    
    Args:
        aspect_degrees: Aspect in degrees (0-360)
        
    Returns:
        Cardinal direction string
    """
    if np.isnan(aspect_degrees):
        return "Unknown"
    
    # Normalize to 0-360
    aspect = aspect_degrees % 360
    
    if aspect < 22.5 or aspect >= 337.5:
        return "North"
    elif 22.5 <= aspect < 67.5:
        return "Northeast"
    elif 67.5 <= aspect < 112.5:
        return "East"
    elif 112.5 <= aspect < 157.5:
        return "Southeast"
    elif 157.5 <= aspect < 202.5:
        return "South"
    elif 202.5 <= aspect < 247.5:
        return "Southwest"
    elif 247.5 <= aspect < 292.5:
        return "West"
    elif 292.5 <= aspect < 337.5:
        return "Northwest"
    else:
        return "Unknown"
