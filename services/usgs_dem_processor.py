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
        self._lock = threading.Lock()
        
        # USGS TNM API endpoints
        self.base_url = "https://tnmaccess.nationalmap.gov/api/v1"
        self.products_url = f"{self.base_url}/products"  # Correct endpoint
        
        # Ensure cache directory exists
        os.makedirs(self.cache_directory, exist_ok=True)
        
        # Create resolution-based subdirectories for smart caching
        for resolution in ['1m', '10m', '30m', 'unknown']:
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
            
            # Step 7: Cleanup temporary files (only if they're different from the final output)
            temp_files = []
            if merged_dem_path != clipped_dem_path and len(local_dem_paths) > 1:
                temp_files.append(merged_dem_path)
            if wgs84_dem_path != clipped_dem_path and wgs84_dem_path != merged_dem_path:
                temp_files.append(wgs84_dem_path)
            
            if temp_files:
                self._cleanup_temp_files(temp_files, polygon_id)
            
            logger.info(f"USGS DEM processing completed for polygon {polygon_id}")
            logger.info(f"Returning WGS84 DEM path: {clipped_dem_path}")
            
            return clipped_dem_path
            
        except Exception as e:
            logger.error(f"Error processing USGS DEM for polygon {polygon_id}: {str(e)}")
            raise
    
    def _is_in_us_bounds(self, polygon_geometry: Dict[str, Any]) -> bool:
        """Check if polygon is within US bounds (more accurate check)"""
        try:
            # Get polygon bounds
            gdf = gpd.GeoDataFrame([1], geometry=[shape(polygon_geometry['geometry'])], crs=self.wgs84_crs)
            bounds = gdf.total_bounds
            
            # More accurate US bounds including Alaska and Hawaii
            # Continental US: -125 to -66 longitude, 24 to 49 latitude
            # Alaska: -180 to -130 longitude, 52 to 72 latitude  
            # Hawaii: -161 to -154 longitude, 18 to 23 latitude
            
            # Check Continental US
            continental_bounds = (-125, 24, -66, 49)
            alaska_bounds = (-180, 52, -130, 72)
            hawaii_bounds = (-161, 18, -154, 23)
            
            polygon_box = box(bounds[0], bounds[1], bounds[2], bounds[3])
            
            # Check each region
            in_continental = polygon_box.intersects(box(*continental_bounds))
            in_alaska = polygon_box.intersects(box(*alaska_bounds))
            in_hawaii = polygon_box.intersects(box(*hawaii_bounds))
            
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
    
    def _query_usgs_products(self, polygon_geometry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Query USGS TNM API for available DEM products with fallback to lower resolutions"""
        try:
            # Get polygon bounds for API query
            gdf = gpd.GeoDataFrame([1], geometry=[shape(polygon_geometry['geometry'])], crs=self.wgs84_crs)
            bounds = gdf.total_bounds
            
            # CORRECT dataset names from USGS TNM API - ONLY ELEVATION DATA
            datasets = [
                {
                    'name': 'Digital Elevation Model (DEM) 1 meter',
                    'resolution': '1m',
                    'priority': 1,
                    'keywords': ['dem', 'elevation', '3dep']
                },
                {
                    'name': 'National Elevation Dataset (NED) 1/3 arc-second',  # ~10m
                    'resolution': '10m',
                    'priority': 2,
                    'keywords': ['ned', 'elevation']
                },
                {
                    'name': 'National Elevation Dataset (NED) 1 arc-second',  # ~30m
                    'resolution': '30m',
                    'priority': 3,
                    'keywords': ['ned', 'elevation']
                }
            ]
            
            all_products = []
            
            for dataset_info in datasets:
                dataset_name = dataset_info['name']
                resolution = dataset_info['resolution']
                
                logger.info(f"Querying for {dataset_name} products")
                
                # CORRECT API parameters for products endpoint
                params = {
                    'dataset': dataset_name,  # Note: singular 'dataset' not 'datasets'
                    'bbox': f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}",  # W,S,E,N
                    'max': 100,  # Maximum results
                    'outputFormat': 'JSON'
                }
                
                logger.info(f"Querying USGS API with params: {params}")
                
                # Use the products endpoint
                response = requests.get(self.products_url, params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # The products endpoint returns an object with 'items' array
                    products = data.get('items', [])
                    logger.info(f"Found {len(products)} {dataset_name} products")
                    
                    # Process products and extract download URLs
                    logger.info(f"Processing {len(products)} products for {dataset_name}")
                    for i, product in enumerate(products):
                        title = product.get('title', 'Unknown')
                        download_url = product.get('downloadURL', '')
                        
                        logger.info(f"Product {i+1}: {title}")
                        logger.info(f"  - downloadURL: {download_url[:50]}..." if download_url else "  - downloadURL: None")
                        logger.info(f"  - sizeInBytes: {product.get('sizeInBytes', 'None')}")
                        
                        # CRITICAL: Filter for elevation data only
                        if not self._is_elevation_product(product, dataset_info['keywords']):
                            logger.info(f"  - SKIPPED: Not elevation data")
                            continue
                        
                        # Check if product has a download URL
                        if download_url:
                            # Add product with metadata
                            size_bytes = product.get('sizeInBytes', 0)
                            size_mb = (size_bytes / (1024 * 1024)) if size_bytes else 0
                            
                            all_products.append({
                                'title': product.get('title', 'Unknown'),
                                'download_url': download_url,
                                'resolution': resolution,
                                'dataset': dataset_name,
                                'size_mb': size_mb,
                                'modification_date': product.get('modificationInfo', ''),
                                'bounds': product.get('boundingBox', {}),
                                'format': product.get('format', 'Unknown'),
                                'priority': dataset_info['priority']
                            })
                            
                else:
                    logger.warning(f"Failed to query {dataset_name}: HTTP {response.status_code}")
                    logger.debug(f"Response: {response.text[:500]}")
            
            if not all_products:
                logger.warning("No DEM products found for any resolution")
                return []
            
            logger.info(f"Total products collected: {len(all_products)}")
            for i, product in enumerate(all_products):
                logger.info(f"Collected product {i+1}: {product['title']} (URL: {product['download_url'][:50]}...)")
            
            # Sort by priority (prefer higher resolution)
            all_products.sort(key=lambda x: x['priority'])
            
            # Log summary
            resolution_counts = {}
            for product in all_products:
                res = product['resolution']
                resolution_counts[res] = resolution_counts.get(res, 0) + 1
            
            logger.info(f"Found total {len(all_products)} products:")
            for res, count in resolution_counts.items():
                logger.info(f"  - {res}: {count} products")
            
            # Return best available products (limit to avoid too many downloads)
            max_products = 20  # Limit number of products to download
            selected_products = all_products[:max_products]
            
            return selected_products
            
        except requests.RequestException as e:
            logger.error(f"Network error querying USGS API: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Error querying USGS API: {str(e)}")
            logger.exception("Full traceback:")
            return []
    
    def _download_dem_file(self, product: Dict[str, Any], polygon_id: str) -> Optional[str]:
        """Download a DEM file from USGS with intelligent caching"""
        try:
            download_url = product['download_url']
            title = product['title']
            resolution = product.get('resolution', 'unknown')
            
            # Create a cache filename based on the product title (not polygon_id)
            # This allows reuse across different requests
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title.replace(' ', '_')
            
            # Determine correct file extension based on URL and content
            if download_url:
                original_filename = os.path.basename(download_url.split('?')[0])
                
                # Check if it's a GeoTIFF file (elevation data)
                if (original_filename.endswith('.tif') or original_filename.endswith('.tiff') or 
                    '/elevation/' in download_url.lower() or '/3dep/' in download_url.lower()):
                    filename = original_filename
                else:
                    # For non-TIFF files, use .tif extension but log warning
                    filename = f"{safe_title}.tif"
                    logger.warning(f"Non-TIFF file detected: {original_filename} - saving as .tif")
            else:
                filename = f"{safe_title}.tif"
            
            # Store in resolution-based subdirectory
            cache_dir = os.path.join(self.cache_directory, resolution)
            os.makedirs(cache_dir, exist_ok=True)
            local_path = os.path.join(cache_dir, filename)
            
            # Check if file exists and is recent (30 days for USGS data)
            if os.path.exists(local_path):
                file_age = time.time() - os.path.getmtime(local_path)
                file_size = os.path.getsize(local_path)
                
                # Check if file is valid (not zero size) and recent
                if file_size > 0 and file_age < 30 * 24 * 3600:  # 30 days
                    logger.info(f"Using cached USGS DEM: {local_path} (age: {file_age/86400:.1f} days)")
                    return local_path
                else:
                    logger.info(f"Cache invalid or expired for {local_path}, re-downloading")
                    os.remove(local_path)
            
            # Download from USGS
            logger.info(f"Downloading USGS DEM: {title}")
            logger.info(f"Download URL: {download_url}")
            logger.info(f"Expected size: {product.get('size_mb', 'Unknown')} MB")
            
            # Use streaming download for large files
            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Get total size if available
            total_size = int(response.headers.get('content-length', 0))
            
            # Download with progress tracking
            downloaded = 0
            chunk_size = 8192  # 8KB chunks
            
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Log progress every 10MB
                        if total_size > 0 and downloaded % (10 * 1024 * 1024) == 0:
                            progress = (downloaded / total_size) * 100
                            logger.info(f"Download progress: {progress:.1f}% ({downloaded/(1024*1024):.1f} MB)")
            
            # Verify download
            file_size = os.path.getsize(local_path)
            if file_size == 0:
                logger.error(f"Downloaded file is empty: {local_path}")
                os.remove(local_path)
                return None
            
            logger.info(f"Successfully downloaded USGS DEM: {local_path} ({file_size/(1024*1024):.1f} MB)")
            return local_path
            
        except requests.RequestException as e:
            logger.error(f"Network error downloading USGS DEM: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error downloading USGS DEM: {str(e)}")
            logger.exception("Full traceback:")
            return None
    
    def _merge_dem_files(self, dem_paths: List[str], polygon_id: str) -> str:
        """Merge multiple DEM files into single file"""
        try:
            # Create output path
            output_dir = f"/app/data/polygon_sessions/{polygon_id}"
            os.makedirs(output_dir, exist_ok=True)
            merged_path = os.path.join(output_dir, f"{polygon_id}_merged_usgs_dem.tif")
            
            logger.info(f"Merging {len(dem_paths)} USGS DEM files to {merged_path}")
            
            # Open all source files
            src_files_to_mosaic = []
            for fp in dem_paths:
                src = rasterio.open(fp)
                src_files_to_mosaic.append(src)
            
            # Merge files
            mosaic, out_trans = merge(src_files_to_mosaic)
            
            # Get metadata from first file
            out_meta = src_files_to_mosaic[0].meta.copy()
            
            # Update metadata
            out_meta.update({
                "driver": "GTiff",
                "height": mosaic.shape[1],
                "width": mosaic.shape[2],
                "transform": out_trans,
                "compress": "lzw",
                "nodata": -9999.0
            })
            
            # Write merged file
            with rasterio.open(merged_path, "w", **out_meta) as dest:
                dest.write(mosaic)
            
            # Close all source files
            for src in src_files_to_mosaic:
                src.close()
            
            logger.info(f"Successfully merged USGS DEM files to {merged_path}")
            return merged_path
            
        except Exception as e:
            logger.error(f"Error merging USGS DEM files: {str(e)}")
            raise
    
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
            
            logger.info(f"Reprojecting USGS DEM to WGS84: {wgs84_path}")
            
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
                out_image, out_transform = mask(src, polygon_geom, crop=True, nodata=-9999.0)
                
                # Update metadata
                out_meta = src.meta.copy()
                out_meta.update({
                    "driver": "GTiff",
                    "height": out_image.shape[1],
                    "width": out_image.shape[2],
                    "transform": out_transform,
                    "nodata": -9999.0,
                    "compress": "lzw"
                })
                
                # Write clipped file
                with rasterio.open(clipped_path, "w", **out_meta) as dest:
                    dest.write(out_image)
            
            logger.info(f"Successfully clipped USGS DEM: {clipped_path}")
            return clipped_path
            
        except Exception as e:
            logger.error(f"Error clipping USGS DEM: {str(e)}")
            raise
    
    def _is_elevation_product(self, product: Dict[str, Any], keywords: List[str]) -> bool:
        """Check if product is elevation data (DEM/NED) and filter out other USGS data"""
        try:
            title = product.get('title', '').lower()
            description = product.get('description', '').lower()
            download_url = product.get('downloadURL', '').lower()
            
            # Look for elevation-related keywords
            elevation_keywords = ['dem', 'digital elevation', 'elevation', 'terrain', 'lidar', 'ned', '3dep']
            has_elevation_keywords = any(keyword in title or keyword in description for keyword in elevation_keywords)
            
            # Check if URL points to elevation data
            is_elevation_url = '/elevation/' in download_url or '/3dep/' in download_url or '/dem/' in download_url
            
            # EXCLUDE non-elevation data types
            exclude_keywords = [
                'boundary', 'structure', 'gazetteer', 'gnis', 'names', 'transportation', 
                'hydrography', 'landcover', 'imagery', 'ortho', 'boundaries', 'structures',
                'buildings', 'roads', 'streams', 'place names', 'geographic names'
            ]
            has_exclude_keywords = any(keyword in title or keyword in description for keyword in exclude_keywords)
            
            # Check file size - elevation data should be reasonable size (not 2GB+)
            size_bytes = product.get('sizeInBytes', 0)
            if size_bytes and size_bytes > 500 * 1024 * 1024:  # 500MB limit
                logger.info(f"  - SKIPPED: File too large ({size_bytes/(1024*1024):.1f} MB) - likely not elevation data")
                return False
            
            # Must have elevation keywords AND not have exclude keywords AND (elevation URL OR reasonable size)
            is_elevation = (has_elevation_keywords or is_elevation_url) and not has_exclude_keywords
            
            if not is_elevation:
                logger.info(f"  - SKIPPED: Not elevation data (has_elevation: {has_elevation_keywords}, is_elevation_url: {is_elevation_url}, has_exclude: {has_exclude_keywords})")
            
            return is_elevation
                
        except Exception as e:
            logger.error(f"Error checking if product is elevation data: {e}")
            return False

    def _cleanup_temp_files(self, temp_files: List[str], polygon_id: str):
        """Clean up temporary files"""
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file) and 'merged' in temp_file or 'wgs84' in temp_file:
                    os.remove(temp_file)
                    logger.debug(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                logger.warning(f"Error cleaning up {temp_file}: {str(e)}")


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