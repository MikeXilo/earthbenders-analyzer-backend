#!/usr/bin/env python3
"""
USGS 3DEP DEM Processing Service - ArcGIS Image Server Approach

Handles USGS 3DEP DEM processing using ArcGIS Image Server REST API:
1. Query ArcGIS Image Server for high-resolution 3DEP data
2. Download GeoTIFF DEM directly (no ZIP extraction needed)
3. Reproject to WGS84 if needed
4. Clip with original WGS84 polygon
5. Return processed DEM path for terrain analysis
"""

import os
import logging
import tempfile
import requests
import time
from typing import Dict, List, Any, Optional
import rasterio
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.crs import CRS
import geopandas as gpd
from shapely.geometry import shape
import numpy as np

logger = logging.getLogger(__name__)

class USGSDEMProcessor:
    """USGS 3DEP DEM processing using ArcGIS Image Server REST API"""
    
    def __init__(self, cache_directory: str = "/app/data/LidarUSA"):
        self.cache_directory = cache_directory
        self.wgs84_crs = CRS.from_epsg(4326)  # WGS84
        
        # ArcGIS Image Server REST API endpoints
        self.base_url = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
        self.export_url = f"{self.base_url}/exportImage"
        
        # Ensure cache directory exists
        os.makedirs(self.cache_directory, exist_ok=True)
        
        logger.info(f"USGS DEM Processor initialized with cache: {self.cache_directory}")
    
    def process_usgs_dem(self, polygon_geometry: Dict[str, Any], polygon_id: str) -> str:
        """
        Main USGS DEM processing pipeline using ArcGIS Image Server
        
        Args:
            polygon_geometry: GeoJSON polygon in WGS84
            polygon_id: Unique polygon identifier
            
        Returns:
            Path to clipped WGS84 DEM TIFF file
        """
        try:
            logger.info(f"Starting USGS 3DEP DEM processing for polygon {polygon_id}")
            
            # Step 1: Check if polygon is in US bounds
            if not self._is_in_us_bounds(polygon_geometry):
                raise ValueError("Polygon is not within US bounds - USGS 3DEP DEM data not available")
            
            # Step 2: Download high-resolution DEM from ArcGIS Image Server
            logger.info("Downloading high-resolution 3DEP DEM from ArcGIS Image Server")
            dem_path = self._download_arcgis_dem(polygon_geometry, polygon_id)
            
            if not dem_path:
                raise ValueError("Failed to download USGS 3DEP DEM data")
            
            # Step 3: Reproject to WGS84 if needed
            logger.info("Checking if reprojection to WGS84 is needed")
            wgs84_dem_path = self._ensure_wgs84(dem_path, polygon_id)
            
            # Step 4: Clip with original WGS84 polygon
            logger.info("Clipping USGS 3DEP DEM with original WGS84 polygon")
            clipped_dem_path = self._clip_dem_with_polygon(wgs84_dem_path, polygon_geometry, polygon_id)
            
            # Step 5: Cleanup temporary files
            temp_files = []
            if dem_path != clipped_dem_path:
                temp_files.append(dem_path)
            if wgs84_dem_path != clipped_dem_path and wgs84_dem_path != dem_path:
                temp_files.append(wgs84_dem_path)
            
            if temp_files:
                self._cleanup_temp_files(temp_files, polygon_id)
            
            logger.info(f"USGS 3DEP DEM processing completed for polygon {polygon_id}")
            logger.info(f"Returning WGS84 DEM path: {clipped_dem_path}")
            
            return clipped_dem_path
            
        except Exception as e:
            logger.error(f"Error processing USGS 3DEP DEM for polygon {polygon_id}: {str(e)}")
            raise
    
    def _is_in_us_bounds(self, polygon_geometry: Dict[str, Any]) -> bool:
        """Check if polygon is within US bounds"""
        try:
            # Get polygon bounds
            gdf = gpd.GeoDataFrame([1], geometry=[shape(polygon_geometry['geometry'])], crs=self.wgs84_crs)
            bounds = gdf.total_bounds
            
            # US bounds (continental US, Alaska, Hawaii)
            continental_bounds = (-125, 24, -66, 49)
            alaska_bounds = (-180, 52, -130, 72)
            hawaii_bounds = (-161, 18, -154, 23)
            
            min_lon, min_lat, max_lon, max_lat = bounds
            
            # Check each region
            in_continental = (continental_bounds[0] <= min_lon <= continental_bounds[2] and 
                           continental_bounds[1] <= min_lat <= continental_bounds[3])
            in_alaska = (alaska_bounds[0] <= min_lon <= alaska_bounds[2] and 
                        alaska_bounds[1] <= min_lat <= alaska_bounds[3])
            in_hawaii = (hawaii_bounds[0] <= min_lon <= hawaii_bounds[2] and 
                        hawaii_bounds[1] <= min_lat <= hawaii_bounds[3])
            
            in_us = in_continental or in_alaska or in_hawaii
            
            if in_us:
                region = "Continental US" if in_continental else ("Alaska" if in_alaska else "Hawaii")
                logger.info(f"Polygon is within US bounds (region: {region})")
            else:
                logger.info(f"Polygon is outside US bounds. Bounds: {bounds}")
            
            return in_us
            
        except Exception as e:
            logger.error(f"Error checking US bounds: {str(e)}")
            return False
    
    def _download_arcgis_dem(self, polygon_geometry: Dict[str, Any], polygon_id: str) -> Optional[str]:
        """Download high-resolution DEM from ArcGIS Image Server"""
        try:
            # Get polygon bounds
            gdf = gpd.GeoDataFrame([1], geometry=[shape(polygon_geometry['geometry'])], crs=self.wgs84_crs)
            bounds = gdf.total_bounds
            min_lon, min_lat, max_lon, max_lat = bounds
            
            logger.info(f"Downloading USGS 3DEP DEM for bbox: {min_lon}, {min_lat}, {max_lon}, {max_lat}")
            
            # Create cache key based on bbox (rounded to avoid tiny differences)
            bbox_key = f"{min_lon:.4f}_{min_lat:.4f}_{max_lon:.4f}_{max_lat:.4f}"
            cache_filename = f"usgs_3dep_{bbox_key}.tif"
            local_path = os.path.join(self.cache_directory, cache_filename)
            
            # Check if file exists and is recent (30 days for USGS data)
            if os.path.exists(local_path):
                file_age = time.time() - os.path.getmtime(local_path)
                if file_age < 30 * 24 * 3600:  # 30 days
                    logger.info(f"Using cached USGS 3DEP DEM: {local_path}")
                    return local_path
            
            # Calculate appropriate image size based on bbox area
            area_size = (max_lon - min_lon) * (max_lat - min_lat)
            if area_size < 0.001:  # Very small area
                size = "500,500"
            elif area_size < 0.01:  # Small area
                size = "1000,1000"
            else:  # Larger area
                size = "2000,2000"
            
            # Build ArcGIS Image Server export request
            export_params = {
                'bbox': f"{min_lon},{min_lat},{max_lon},{max_lat}",
                'bboxSR': 4326,
                'size': size,
                'imageSR': 4326,
                'format': 'tiff',
                'pixelType': 'F32',  # 32-bit float for elevation
                'noDataInterpretation': 'esriNoDataMatchAny',
                'interpolation': '+RSP_BilinearInterpolation',
                'f': 'image'
            }
            
            logger.info(f"Requesting USGS 3DEP DEM from ArcGIS Image Server")
            logger.info(f"Parameters: {export_params}")
            
            # Make request to ArcGIS Image Server
            response = requests.get(self.export_url, params=export_params, timeout=300)
            response.raise_for_status()
            
            # Check if we got a valid image response
            content_type = response.headers.get('content-type', '')
            if 'image' not in content_type and 'application/octet-stream' not in content_type:
                logger.error(f"Unexpected content type: {content_type}")
                logger.error(f"Response: {response.text[:500]}")
                return None
            
            # Save to local file
            with open(local_path, 'wb') as f:
                f.write(response.content)
            
            logger.info(f"Downloaded USGS 3DEP DEM: {local_path} ({len(response.content)} bytes)")
            return local_path
            
        except Exception as e:
            logger.error(f"Error downloading USGS 3DEP DEM: {str(e)}")
            return None
    
    def _ensure_wgs84(self, dem_path: str, polygon_id: str) -> str:
        """Ensure DEM is in WGS84, reproject if needed"""
        try:
            with rasterio.open(dem_path) as src:
                if src.crs and src.crs.to_epsg() == 4326:
                    logger.info("DEM is already in WGS84, no reprojection needed")
                    return dem_path
            
            # Create output path
            output_dir = f"/app/data/polygon_sessions/{polygon_id}"
            os.makedirs(output_dir, exist_ok=True)
            wgs84_path = os.path.join(output_dir, f"{polygon_id}_wgs84_usgs_dem.tif")
            
            logger.info(f"Reprojecting USGS 3DEP DEM to WGS84: {wgs84_path}")
            
            with rasterio.open(dem_path) as src:
                # Calculate transform for WGS84
                transform, width, height = calculate_default_transform(
                    src.crs, self.wgs84_crs, src.width, src.height, *src.bounds
                )
                
                # Update metadata for WGS84
                kwargs = src.meta.copy()
                kwargs.update({
                    'crs': self.wgs84_crs,
                    'transform': transform,
                    'width': width,
                    'height': height,
                    'compress': 'lzw'
                })
                
                # Reproject to WGS84
                with rasterio.open(wgs84_path, 'w', **kwargs) as dst:
                    for i in range(1, src.count + 1):
                        reproject(
                            source=rasterio.band(src, i),
                            destination=rasterio.band(dst, i),
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=transform,
                            dst_crs=self.wgs84_crs,
                            resampling=Resampling.bilinear
                        )
            
            logger.info(f"Successfully reprojected USGS 3DEP DEM to WGS84: {wgs84_path}")
            return wgs84_path
            
        except Exception as e:
            logger.error(f"Error reprojecting USGS 3DEP DEM to WGS84: {str(e)}")
            raise
    
    def _clip_dem_with_polygon(self, dem_path: str, polygon_geometry: Dict[str, Any], polygon_id: str) -> str:
        """Clip DEM with original WGS84 polygon"""
        try:
            # Create output directory
            output_dir = f"/app/data/polygon_sessions/{polygon_id}"
            os.makedirs(output_dir, exist_ok=True)
            
            # Use SRTM filename pattern for compatibility with existing pipeline
            # Note: This file contains USGS 3DEP data, but uses SRTM naming for compatibility
            clipped_path = os.path.join(output_dir, f"{polygon_id}_srtm.tif")
            
            logger.info(f"Clipping USGS 3DEP DEM with WGS84 polygon: {clipped_path}")
            
            # Create polygon geometry
            polygon_geom = [shape(polygon_geometry['geometry'])]
            
            with rasterio.open(dem_path) as src:
                # Clip the DEM with the polygon
                out_image, out_transform = mask(src, polygon_geom, crop=True, nodata=np.nan)
                
                # Additional cleanup for USGS DEM data (like Portuguese LiDAR)
                # Ensure NoData values are properly set to NaN
                out_image = out_image.astype(np.float32)
                out_image[out_image == 0] = np.nan
                out_image[out_image == -9999.0] = np.nan
                out_image[out_image == -32768] = np.nan
                
                # Update metadata
                out_meta = src.meta.copy()
                out_meta.update({
                    "driver": "GTiff",
                    "height": out_image.shape[1],
                    "width": out_image.shape[2],
                    "transform": out_transform,
                    "nodata": np.nan,
                    "compress": "lzw"
                })
                
                # Write clipped file
                with rasterio.open(clipped_path, "w", **out_meta) as dest:
                    dest.write(out_image)
            
            logger.info(f"Successfully clipped USGS 3DEP DEM: {clipped_path}")
            return clipped_path
            
        except Exception as e:
            logger.error(f"Error clipping USGS 3DEP DEM: {str(e)}")
            raise
    
    def _cleanup_temp_files(self, temp_files: List[str], polygon_id: str):
        """Clean up temporary files"""
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file) and ('wgs84' in temp_file or 'usgs_3dep' in temp_file):
                    os.remove(temp_file)
                    logger.debug(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                logger.warning(f"Error cleaning up {temp_file}: {str(e)}")


# Global USGS DEM processor instance
usgs_dem_processor = USGSDEMProcessor()


def process_usgs_dem(polygon_geometry: Dict[str, Any], polygon_id: str) -> str:
    """
    Main function to process USGS 3DEP DEM using ArcGIS Image Server
    
    Args:
        polygon_geometry: GeoJSON polygon in WGS84
        polygon_id: Unique polygon identifier
        
    Returns:
        Path to clipped WGS84 DEM TIFF file
    """
    return usgs_dem_processor.process_usgs_dem(polygon_geometry, polygon_id)