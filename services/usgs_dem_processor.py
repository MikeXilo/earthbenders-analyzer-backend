#!/usr/bin/env python3
"""
USGS 3DEP DEM Processing Service

Handles USGS 3DEP DEM processing with proper CRS transformation:
1. Query USGS TNM API for available DEM products
2. Download GeoTIFF DEM files
3. Merge multiple tiles if needed
4. Reproject to WGS84 if needed
5. Clip with original WGS84 polygon
6. Return processed DEM path for terrain analysis
"""

import os
import logging
import tempfile
import shutil
import requests
import json
import time
from typing import Dict, List, Any, Optional, Tuple
import rasterio
from rasterio.merge import merge
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.crs import CRS
import geopandas as gpd
from shapely.geometry import shape, box
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

logger = logging.getLogger(__name__)

class USGSDEMProcessor:
    """USGS 3DEP DEM processing with API integration"""
    
    def __init__(self, cache_directory: str = "/app/data/LidarUSA"):
        self.cache_directory = cache_directory
        self.wgs84_crs = CRS.from_epsg(4326)  # WGS84
        self.usgs_crs = CRS.from_epsg(3857)   # Web Mercator (common for USGS)
        self._lock = threading.Lock()
        
        # USGS TNM API endpoints
        self.base_url = "https://tnmaccess.nationalmap.gov/api/v1"
        self.products_url = f"{self.base_url}/products"
        self.datasets_url = f"{self.base_url}/datasets"
        
        # Ensure cache directory exists
        os.makedirs(self.cache_directory, exist_ok=True)
        
        # Create resolution-based subdirectories for smart caching
        for resolution in ['1m', '3m', '5m']:
            os.makedirs(os.path.join(self.cache_directory, resolution), exist_ok=True)
        
        logger.info(f"USGS DEM Processor initialized with cache: {self.cache_directory}")
    
    def process_usgs_dem(self, polygon_geometry: Dict[str, Any], polygon_id: str) -> str:
        """
        Main USGS DEM processing pipeline
        
        Args:
            polygon_geometry: GeoJSON polygon in WGS84
            polygon_id: Unique polygon identifier
            
        Returns:
            Path to clipped WGS84 DEM TIFF file
        """
        try:
            logger.info(f"Starting USGS DEM processing for polygon {polygon_id}")
            
            # Step 1: Check if polygon is in US bounds
            if not self._is_in_us_bounds(polygon_geometry):
                raise ValueError("Polygon is not within US bounds - USGS 3DEP data not available")
            
            # Step 2: Query USGS API for available DEM products
            logger.info("Querying USGS API for available DEM products")
            available_products = self._query_usgs_products(polygon_geometry)
            
            if not available_products:
                raise ValueError("No USGS 3DEP DEM products available for this area")
            
            logger.info(f"Found {len(available_products)} USGS DEM products")
            
            # Step 3: Download DEM files
            logger.info(f"Downloading {len(available_products)} DEM files")
            local_dem_paths = []
            for product in available_products:
                local_path = self._download_dem_file(product, polygon_id)
                if local_path:
                    local_dem_paths.append(local_path)
                else:
                    logger.error(f"Failed to download DEM: {product.get('title', 'Unknown')}")
            
            if not local_dem_paths:
                raise ValueError("Failed to download any USGS DEM files")
            
            # Step 4: Process DEM files (merge if multiple)
            if len(local_dem_paths) == 1:
                logger.info("Processing single USGS DEM file")
                merged_dem_path = local_dem_paths[0]
            else:
                logger.info(f"Merging {len(local_dem_paths)} USGS DEM files")
                merged_dem_path = self._merge_dem_files(local_dem_paths, polygon_id)
            
            # Step 5: Reproject to WGS84 if needed
            logger.info("Checking if reprojection to WGS84 is needed")
            wgs84_dem_path = self._ensure_wgs84(merged_dem_path, polygon_id)
            
            # Step 6: Clip with original WGS84 polygon
            logger.info("Clipping USGS DEM with original WGS84 polygon")
            clipped_dem_path = self._clip_dem_with_polygon(wgs84_dem_path, polygon_geometry, polygon_id)
            
            # Step 7: Cleanup temporary files
            self._cleanup_temp_files([merged_dem_path, wgs84_dem_path], polygon_id)
            
            logger.info(f"USGS DEM processing completed for polygon {polygon_id}")
            logger.info(f"Returning WGS84 DEM path: {clipped_dem_path}")
            
            return clipped_dem_path
            
        except Exception as e:
            logger.error(f"Error processing USGS DEM for polygon {polygon_id}: {str(e)}")
            return None
    
    def _is_in_us_bounds(self, polygon_geometry: Dict[str, Any]) -> bool:
        """Check if polygon is within US bounds (rough check)"""
        try:
            # Get polygon bounds
            gdf = gpd.GeoDataFrame([1], geometry=[shape(polygon_geometry['geometry'])], crs=self.wgs84_crs)
            bounds = gdf.total_bounds
            
            # Rough US bounds: -180 to -65 longitude, 15 to 72 latitude
            us_bounds = (-180, 15, -65, 72)
            
            # Check if polygon intersects with US bounds
            polygon_bounds = box(bounds[0], bounds[1], bounds[2], bounds[3])
            us_box = box(us_bounds[0], us_bounds[1], us_bounds[2], us_bounds[3])
            
            intersects = polygon_bounds.intersects(us_box)
            logger.info(f"Polygon bounds: {bounds}, US bounds: {us_bounds}, Intersects: {intersects}")
            
            return intersects
            
        except Exception as e:
            logger.error(f"Error checking US bounds: {str(e)}")
            return False
    
    def _query_usgs_products(self, polygon_geometry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Query USGS TNM API for available 1m DEM products with fallback to lower resolutions"""
        try:
            # Get polygon bounds for API query
            gdf = gpd.GeoDataFrame([1], geometry=[shape(polygon_geometry['geometry'])], crs=self.wgs84_crs)
            bounds = gdf.total_bounds
            
            # Try different resolutions in order of preference: 1m > 3m > 5m
            resolutions = [
                'Digital Elevation Model (DEM) 1 meter',
                'Digital Elevation Model (DEM) 3 meter', 
                'Digital Elevation Model (DEM) 5 meter'
            ]
            
            for dataset_name in resolutions:
                logger.info(f"Trying to find {dataset_name} products")
                
                # Build API query parameters for specific resolution
                params = {
                    'datasets': dataset_name,  # Specific resolution product
                    'bbox': f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}",  # W,S,E,N
                    'format': 'GeoTIFF',  # GeoTIFF format
                    'prodExtents': 'Full Extent',  # Full extent of the product
                    'max': 50  # Limit results
                }
                
                logger.info(f"Querying USGS API with params: {params}")
                
                # Make API request (NO AUTHENTICATION NEEDED!)
                response = requests.get(self.products_url, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                products = data.get('items', [])
                
                logger.info(f"USGS API returned {len(products)} {dataset_name} products")
                
                # Extract download URLs for this resolution
                dem_products = []
                for product in products:
                    if 'downloadURL' in product:
                        resolution = self._extract_resolution_from_dataset(dataset_name)
                        dem_products.append({
                            'title': product.get('title', 'Unknown'),
                            'download_url': product['downloadURL'],
                            'resolution': resolution,
                            'bounds': product.get('bounds', {})
                        })
                
                if dem_products:
                    logger.info(f"Found {len(dem_products)} {dataset_name} products with download URLs")
                    return dem_products
                else:
                    logger.info(f"No {dataset_name} products found, trying next resolution")
            
            # If no products found for any resolution
            logger.warning("No USGS DEM products found for any resolution")
            return []
            
        except Exception as e:
            logger.error(f"Error querying USGS API: {str(e)}")
            return []
    
    def _extract_resolution_from_dataset(self, dataset_name: str) -> str:
        """Extract resolution from dataset name"""
        if '1 meter' in dataset_name:
            return '1m'
        elif '3 meter' in dataset_name:
            return '3m'
        elif '5 meter' in dataset_name:
            return '5m'
        else:
            return 'unknown'
    
    def _extract_resolution(self, product: Dict[str, Any]) -> str:
        """Extract resolution information from product metadata (fallback method)"""
        try:
            # Look for resolution in various fields
            title = product.get('title', '').lower()
            description = product.get('description', '').lower()
            
            if '1m' in title or '1m' in description:
                return '1m'
            elif '3m' in title or '3m' in description:
                return '3m'
            elif '5m' in title or '5m' in description:
                return '5m'
            else:
                return 'unknown'
                
        except Exception:
            return 'unknown'
    
    def _download_dem_file(self, product: Dict[str, Any], polygon_id: str) -> Optional[str]:
        """Download a DEM file from USGS with intelligent caching using USGS product identifiers"""
        try:
            download_url = product['download_url']
            title = product['title']
            resolution = product.get('resolution', 'unknown')
            
            # FIXED: Use USGS product identifier instead of polygon_id for caching
            # This allows tiles to be reused across different users/polygons
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title.replace(' ', '_')
            filename = f"{resolution}_{safe_title}.tif"
            
            # Store in resolution-based subdirectory
            local_path = os.path.join(self.cache_directory, resolution, filename)
            
            # Check if file exists and is recent (30 days for USGS data)
            if os.path.exists(local_path):
                file_age = time.time() - os.path.getmtime(local_path)
                if file_age < 30 * 24 * 3600:  # 30 days
                    logger.info(f"Using cached USGS DEM: {local_path}")
                    return local_path
            
            # Download from USGS
            logger.info(f"Downloading USGS DEM: {title}")
            logger.info(f"Download URL: {download_url}")
            
            response = requests.get(download_url, timeout=300)  # 5 minute timeout
            response.raise_for_status()
            
            # Save to local file
            with open(local_path, 'wb') as f:
                f.write(response.content)
            
            logger.info(f"Downloaded USGS DEM: {local_path}")
            return local_path
            
        except Exception as e:
            logger.error(f"Error downloading USGS DEM: {str(e)}")
            return None
    
    def _merge_dem_files(self, dem_paths: List[str], polygon_id: str) -> str:
        """Merge multiple DEM files into single file"""
        try:
            # Use tempfile.TemporaryDirectory for robust temp file management
            with tempfile.TemporaryDirectory(prefix=f"usgs_merge_{polygon_id}_") as temp_dir:
                merged_path = os.path.join(temp_dir, f"{polygon_id}_merged_usgs_dem.tif")
                
                logger.info(f"Merging {len(dem_paths)} USGS DEM files to {merged_path}")
                
                # Use rasterio.merge to combine files
                merged_array, merged_transform = merge(dem_paths)
                
                # Get metadata from first file
                with rasterio.open(dem_paths[0]) as src:
                    merged_meta = src.meta.copy()
                    merged_meta.update({
                        'driver': 'GTiff',
                        'height': merged_array.shape[1],
                        'width': merged_array.shape[2],
                        'transform': merged_transform,
                        'nodata': -9999.0,  # FIXED: Use standard nodata value instead of np.nan
                        'compress': 'lzw'
                    })
                
                # Clean up merged data
                merged_array = merged_array.astype(np.float32)
                merged_array[merged_array == 0] = -9999.0  # FIXED: Use standard nodata value
                merged_array[merged_array == -9999] = -9999.0
                
                # Write merged file
                with rasterio.open(merged_path, 'w', **merged_meta) as dst:
                    dst.write(merged_array)
                
                logger.info(f"Successfully merged USGS DEM files to {merged_path}")
                return merged_path
            
        except Exception as e:
            logger.error(f"Error merging USGS DEM files: {str(e)}")
            raise
    
    def _ensure_wgs84(self, dem_path: str, polygon_id: str) -> str:
        """Ensure DEM is in WGS84, reproject if needed"""
        try:
            with rasterio.open(dem_path) as src:
                if src.crs == self.wgs84_crs:
                    logger.info("DEM is already in WGS84, no reprojection needed")
                    return dem_path
            
            # Use tempfile.TemporaryDirectory for robust temp file management
            with tempfile.TemporaryDirectory(prefix=f"usgs_wgs84_{polygon_id}_") as temp_dir:
                wgs84_path = os.path.join(temp_dir, f"{polygon_id}_wgs84_usgs_dem.tif")
                
                logger.info(f"Reprojecting USGS DEM to WGS84: {wgs84_path}")
                
                with rasterio.open(dem_path) as src:
                    # Calculate transform for WGS84
                    transform, width, height = calculate_default_transform(
                        src.crs, self.wgs84_crs, src.width, src.height, *src.bounds
                    )
                    
                    # Update metadata for WGS84
                    wgs84_meta = src.meta.copy()
                    wgs84_meta.update({
                        'crs': self.wgs84_crs,
                        'transform': transform,
                        'width': width,
                        'height': height,
                        'compress': 'lzw'
                    })
                    
                    # Reproject to WGS84
                    with rasterio.open(wgs84_path, 'w', **wgs84_meta) as dst:
                        reproject(
                            source=rasterio.band(src, 1),
                            destination=rasterio.band(dst, 1),
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=transform,
                            dst_crs=self.wgs84_crs,
                            resampling=Resampling.bilinear
                        )
                
                logger.info(f"Successfully reprojected USGS DEM to WGS84: {wgs84_path}")
                return wgs84_path
            
        except Exception as e:
            logger.error(f"Error reprojecting USGS DEM to WGS84: {str(e)}")
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
            
            logger.info(f"Clipping USGS DEM with WGS84 polygon: {clipped_path}")
            
            # Create polygon geometry
            polygon_geom = [shape(polygon_geometry['geometry'])]
            
            with rasterio.open(dem_path) as src:
                # Clip the DEM with the polygon
                clipped_data, clipped_transform = mask(src, polygon_geom, crop=True, nodata=-9999.0)  # FIXED: Use standard nodata value
                
            # Clean up data
            clipped_data = clipped_data.astype(np.float32)
            clipped_data[clipped_data == 0] = -9999.0  # FIXED: Use standard nodata value
            clipped_data[clipped_data == -9999] = -9999.0
            
            # Update metadata
            clipped_meta = src.meta.copy()
            clipped_meta.update({
                'height': clipped_data.shape[1],
                'width': clipped_data.shape[2],
                'transform': clipped_transform,
                'nodata': -9999.0,  # FIXED: Use standard nodata value
                'compress': 'lzw'
            })
            
            # Write clipped file
            with rasterio.open(clipped_path, 'w', **clipped_meta) as dst:
                dst.write(clipped_data)
            
            logger.info(f"Successfully clipped USGS DEM: {clipped_path}")
            return clipped_path
            
        except Exception as e:
            logger.error(f"Error clipping USGS DEM: {str(e)}")
            raise
    
    def _cleanup_temp_files(self, temp_files: List[str], polygon_id: str):
        """Clean up temporary files"""
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logger.debug(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                logger.warning(f"Error cleaning up {temp_file}: {str(e)}")
        
        # Clean up temporary directories
        temp_dirs = [f"/tmp/usgs_merge_{polygon_id}", f"/tmp/usgs_wgs84_{polygon_id}"]
        for temp_dir in temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Error cleaning up directory {temp_dir}: {str(e)}")


# Global USGS DEM processor instance
usgs_dem_processor = USGSDEMProcessor()


def process_usgs_dem(polygon_geometry: Dict[str, Any], polygon_id: str) -> str:
    """
    Main function to process USGS DEM
    
    Args:
        polygon_geometry: GeoJSON polygon in WGS84
        polygon_id: Unique polygon identifier
        
    Returns:
        Path to clipped WGS84 DEM TIFF file
    """
    return usgs_dem_processor.process_usgs_dem(polygon_geometry, polygon_id)
