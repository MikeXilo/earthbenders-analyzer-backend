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

def calculate_terrain_statistics(dem_path: str, slope_path: str, aspect_path: str, bounds: Dict[str, float], data_source: str = 'srtm') -> Dict[str, Any]:
    """
    Calculate terrain statistics from DEM, slope, and aspect files
    
    Args:
        dem_path: Path to DEM elevation file
        slope_path: Path to slope file
        aspect_path: Path to aspect file
        bounds: Bounding box coordinates
        data_source: Data source type ('srtm', 'lidar', etc.) for appropriate NoData handling
        
    Returns:
        Dictionary with calculated statistics
    """
    try:
        logger.info(f"Calculating terrain statistics for files: {dem_path}, {slope_path}, {aspect_path}")
        
        # 🚨 CRITICAL FIX: Ensure bounds is a dict, or initialize to empty
        if bounds is None:
            bounds = {}
            logger.warning("Bounds were not provided to calculate_terrain_statistics, defaulting to empty dict.")
        
        # Check if SRTM file exists (required)
        if not os.path.exists(dem_path):
            logger.error(f"DEM file not found: {dem_path}")
            return {}
        
        # Check if slope and aspect files exist (optional)
        slope_exists = slope_path and os.path.exists(slope_path)
        aspect_exists = aspect_path and os.path.exists(aspect_path)
        
        # Read DEM data
        logger.info(f"Reading DEM data from: {dem_path}")
        with rasterio.open(dem_path) as src:
            dem_data = src.read(1)
            dem_nodata = src.nodata
            logger.info(f"DEM data shape: {dem_data.shape}")
            logger.info(f"DEM nodata value: {dem_nodata}")
            logger.info(f"DEM data range: {np.nanmin(dem_data)} to {np.nanmax(dem_data)}")
            logger.info(f"DEM data type: {dem_data.dtype}")
            
            # CRITICAL DEBUGGING: Check raw array content
            logger.info(f"Raw array min: {np.min(dem_data)}, max: {np.max(dem_data)}")
            logger.info(f"Raw array unique values (first 10): {np.unique(dem_data)[:10]}")
            logger.info(f"Raw array has NaN: {np.any(np.isnan(dem_data))}")
            logger.info(f"Raw array has zeros: {np.any(dem_data == 0)}")
            logger.info(f"Raw array has -9999: {np.any(dem_data == -9999)}")
            logger.info(f"Raw array has -32768: {np.any(dem_data == -32768)}")
            
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
        
        # Mask out nodata values - handle based on data source
        logger.info(f"=== MASKING DEBUGGING ===")
        logger.info(f"Data source: {data_source}")
        logger.info(f"Original array size: {dem_data.size}")
        
        if data_source == 'lidar':
            # LIDAR-specific NoData handling
            logger.info(f"Using LIDAR-specific NoData filtering")
            dem_masked = dem_data[~np.isnan(dem_data)]  # Remove NaN values
            logger.info(f"After NaN filtering: {len(dem_masked)} values remain")
            # Don't filter by -9999 for LIDAR as it might be valid elevation
        else:
            # SRTM-specific NoData handling (default behavior)
            if dem_nodata is not None:
                logger.info(f"Using explicit nodata value: {dem_nodata}")
                dem_masked = dem_data[dem_data != dem_nodata]
                logger.info(f"After filtering nodata={dem_nodata}: {len(dem_masked)} values remain")
            else:
                logger.info(f"Using NaN filtering for SRTM data")
                dem_masked = dem_data[~np.isnan(dem_data)]
                logger.info(f"After NaN filtering: {len(dem_masked)} values remain")
                dem_masked = dem_masked[dem_masked > -9999]  # Filter out common invalid values
                logger.info(f"After -9999 filtering: {len(dem_masked)} values remain")
        
        logger.info(f"FINAL masked data length: {len(dem_masked)}")
        if len(dem_masked) > 0:
            logger.info(f"FINAL masked data range: {np.nanmin(dem_masked)} to {np.nanmax(dem_masked)}")
        else:
            logger.error("CRITICAL: ALL DATA FILTERED OUT! No valid elevation data remains!")
        slope_masked = slope_data[slope_data != slope_nodata] if slope_data is not None and slope_nodata is not None else (slope_data if slope_data is not None else np.array([]))
        aspect_masked = aspect_data[aspect_data != aspect_nodata] if aspect_data is not None and aspect_nodata is not None else (aspect_data if aspect_data is not None else np.array([]))
        
        # Calculate elevation statistics
        if len(dem_masked) > 0:
            elevation_min = float(np.min(dem_masked))
            elevation_max = float(np.max(dem_masked))
            elevation_mean = float(np.mean(dem_masked))
            logger.info(f"Elevation statistics calculated: min={elevation_min}, max={elevation_max}, mean={elevation_mean}")
        else:
            elevation_min = None
            elevation_max = None
            elevation_mean = None
            logger.error("CRITICAL: No valid elevation data found after masking!")
        
        # Calculate slope statistics (only if slope data exists)
        slope_mean = float(np.mean(slope_masked)) if len(slope_masked) > 0 and slope_exists else 0
        slope_min = float(np.min(slope_masked)) if len(slope_masked) > 0 and slope_exists else 0
        slope_max = float(np.max(slope_masked)) if len(slope_masked) > 0 and slope_exists else 0
        slope_std = float(np.std(slope_masked)) if len(slope_masked) > 0 and slope_exists else 0
        
        # Calculate aspect statistics (only if aspect data exists)
        aspect_mean = float(np.mean(aspect_masked)) if len(aspect_masked) > 0 and aspect_exists else 0
        
        # Determine aspect direction
        aspect_direction = get_aspect_direction(aspect_mean) if aspect_exists else "Unknown"
        
        # Calculate area using actual raster resolution
        pixel_count = len(dem_masked)
        
        # Get actual pixel size from raster metadata
        with rasterio.open(dem_path) as src:
            transform = src.transform
            pixel_width_deg = abs(transform[0])  # Pixel width in degrees
            pixel_height_deg = abs(transform[4])  # Pixel height in degrees
            
            # Convert degrees to meters (approximate at latitude)
            # At equator: 1 degree ≈ 111,320 meters
            # This is a reasonable approximation for most latitudes
            pixel_width_m = pixel_width_deg * 111320
            pixel_height_m = pixel_height_deg * 111320
            pixel_area_m2 = pixel_width_m * pixel_height_m
            
        area_km2 = (pixel_count * pixel_area_m2) / 1_000_000  # Convert to km²
        
        # Calculate terrain ruggedness (standard deviation of elevation)
        terrain_ruggedness = float(np.std(dem_masked)) if len(dem_masked) > 0 else 0
        
        # Calculate relief (elevation range)
        relief = elevation_max - elevation_min
        
        # Import datetime for processed_at
        from datetime import datetime
        
        # Helper function to clean NaN values for PostgreSQL JSON compatibility
        def clean_nan_values(value):
            """Convert NaN values to None for PostgreSQL JSON compatibility"""
            if isinstance(value, float) and np.isnan(value):
                return None
            return value
        
        statistics = {
            'bounds': bounds,
            'relief': clean_nan_values(round(relief, 2)),
            'area_km2': clean_nan_values(round(area_km2, 4)),
            'slope_max': clean_nan_values(round(slope_max, 2)),
            'slope_min': clean_nan_values(round(slope_min, 2)),
            'slope_std': clean_nan_values(round(slope_std, 2)),
            'slope_mean': clean_nan_values(round(slope_mean, 2)),
            'aspect_mean': clean_nan_values(round(aspect_mean, 2)),
            'aspect_path': aspect_path,
            'pixel_count': pixel_count,
            'processed_at': datetime.now().isoformat(),
            'elevation_max': clean_nan_values(round(elevation_max, 2)),
            'elevation_min': clean_nan_values(round(elevation_min, 2)),
            'elevation_mean': clean_nan_values(round(elevation_mean, 2)),
            'aspect_direction': aspect_direction,
            'terrain_ruggedness': clean_nan_values(round(terrain_ruggedness, 2))
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
