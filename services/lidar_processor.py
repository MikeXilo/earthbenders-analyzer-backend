#!/usr/bin/env python3
"""
Independent LIDAR DEM Processing Service

Handles LIDAR DEM processing with proper CRS transformation:
1. Convert polygon from WGS84 to EPSG:3763 for tile intersection
2. Find intersecting LIDAR tiles in EPSG:3763
3. Merge multiple tiles if needed
4. Reproject merged DEM to WGS84
5. Clip with original WGS84 polygon
6. Save as final_dem_path in database
"""

import os
import logging
import tempfile
import shutil
from typing import Dict, List, Any, Optional, Tuple
import json
import rasterio
from rasterio.merge import merge
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.crs import CRS
import geopandas as gpd
# CRITICAL IMPORTS FOR IMAGE PROCESSING AND BASE64 ENCODING
import base64
from io import BytesIO
from PIL import Image
from shapely.geometry import shape, box
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
# AWS S3 INTEGRATION
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class LidarProcessor:
    """Independent LIDAR DEM processing with CRS transformation"""
    
    def __init__(self, lidar_directory: str = "/app/data/LidarPt"):
        self.lidar_directory = lidar_directory
        self.wgs84_crs = CRS.from_epsg(4326)  # WGS84
        self.etrs89_crs = CRS.from_epsg(3763)  # ETRS89/TM06
        self._lock = threading.Lock()
        # Initialize S3 client
        self.s3_client = None
        self.s3_bucket = None
        self._init_s3()
    
    def _init_s3(self):
        """Initialize S3 client for LIDAR tile downloads"""
        try:
            # Get S3 credentials from environment
            aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
            aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
            bucket_name = os.getenv('AWS_S3_BUCKET_NAME', 'lidarpt2m2025')
            region = os.getenv('AWS_REGION', 'eu-north-1')
            
            if aws_access_key and aws_secret_key:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key,
                    region_name=region
                )
                self.s3_bucket = bucket_name
                logger.info(f"S3 client initialized for bucket: {bucket_name}")
            else:
                logger.warning("AWS credentials not found, S3 integration disabled")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {str(e)}")
            self.s3_client = None
    
    def process_lidar_dem(self, polygon_geometry: Dict[str, Any], polygon_id: str) -> str:
        """
        Main LIDAR processing pipeline with CRS transformation
        
        Args:
            polygon_geometry: GeoJSON polygon in WGS84
            polygon_id: Unique polygon identifier
            
        Returns:
            Dict with clipped LIDAR DEM path, bounds, statistics, and visualization
        """
        try:
            logger.info(f"Starting LIDAR DEM processing for polygon {polygon_id}")
            
            # Step 1: Convert polygon to EPSG:3763 for tile intersection
            logger.info("Converting polygon to EPSG:3763 for tile intersection")
            etrs89_polygon = self._convert_polygon_to_etrs89(polygon_geometry)
            
            # Step 2: Find intersecting LIDAR tiles
            logger.info("Finding intersecting LIDAR tiles")
            intersecting_tiles = self._find_intersecting_tiles(etrs89_polygon)
            
            if not intersecting_tiles:
                raise ValueError("No LIDAR tiles intersect with the specified polygon")
            
            logger.info(f"Found {len(intersecting_tiles)} intersecting LIDAR tiles")
            
            # Step 3: Download S3 tiles to local storage
            logger.info(f"Downloading {len(intersecting_tiles)} tiles from S3")
            local_tile_paths = []
            for s3_path in intersecting_tiles:
                local_path = self._download_tile_from_s3(s3_path)
                if local_path:
                    local_tile_paths.append(local_path)
                else:
                    logger.error(f"Failed to download tile: {s3_path}")
            
            if not local_tile_paths:
                raise ValueError("Failed to download any LIDAR tiles from S3")
            
            # Step 4: Process tiles (merge if multiple)
            if len(local_tile_paths) == 1:
                logger.info("Processing single LIDAR tile")
                merged_etrs89_path = local_tile_paths[0]
            else:
                logger.info(f"Merging {len(local_tile_paths)} LIDAR tiles")
                merged_etrs89_path = self._merge_lidar_tiles(local_tile_paths, polygon_id)
            
            # Step 4: Reproject merged DEM to WGS84
            logger.info("Reprojecting merged LIDAR DEM to WGS84")
            wgs84_dem_path = self._reproject_to_wgs84(merged_etrs89_path, polygon_id)
            
            # Step 5: Clip with original WGS84 polygon
            logger.info("Clipping LIDAR DEM with original WGS84 polygon")
            clipped_lidar_path = self._clip_lidar_dem(wgs84_dem_path, polygon_geometry, polygon_id)
            
            # Step 6: Cleanup temporary files
            self._cleanup_temp_files([merged_etrs89_path, wgs84_dem_path], polygon_id)
            
            logger.info(f"LIDAR DEM preparation completed for polygon {polygon_id}")
            logger.info(f"Returning WGS84 TIFF path: {clipped_lidar_path}")
            
            # Return only the path - let SRTM pipeline handle visualization and database
            return clipped_lidar_path
            
        except Exception as e:
            logger.error(f"Error processing LIDAR DEM for polygon {polygon_id}: {str(e)}")
            return None
    
    def _convert_polygon_to_etrs89(self, polygon_geometry: Dict[str, Any]) -> gpd.GeoDataFrame:
        """Convert WGS84 polygon to EPSG:3763 for tile intersection"""
        try:
            # Create GeoDataFrame from WGS84 polygon
            gdf_wgs84 = gpd.GeoDataFrame([1], geometry=[shape(polygon_geometry['geometry'])], crs=self.wgs84_crs)
            
            # Reproject to EPSG:3763
            gdf_etrs89 = gdf_wgs84.to_crs(self.etrs89_crs)
            
            logger.info(f"Polygon converted to EPSG:3763. Bounds: {gdf_etrs89.total_bounds}")
            return gdf_etrs89
            
        except Exception as e:
            logger.error(f"Error converting polygon to EPSG:3763: {str(e)}")
            raise
    
    def _find_intersecting_tiles(self, etrs89_polygon: gpd.GeoDataFrame) -> List[str]:
        """Find LIDAR tiles that intersect with the EPSG:3763 polygon"""
        try:
            intersecting_tiles = []
            polygon_bounds = etrs89_polygon.total_bounds
            
            logger.info(f"Searching for tiles intersecting bounds: {polygon_bounds}")
            
            # Use GeoPackage spatial index if available, otherwise fall back to S3/local
            if os.path.exists("/app/data/lidarpt2m2025tiles.gpkg"):
                logger.info("Using GeoPackage spatial index for LIDAR tile discovery")
                intersecting_tiles = self._find_intersecting_tiles_s3(etrs89_polygon)
            elif self.s3_client:
                logger.info("Using S3 for LIDAR tile discovery")
                intersecting_tiles = self._find_intersecting_tiles_s3(etrs89_polygon)
            else:
                logger.info(f"Using local directory: {self.lidar_directory}")
                intersecting_tiles = self._find_intersecting_tiles_local(etrs89_polygon)
            
            logger.info(f"Found {len(intersecting_tiles)} intersecting tiles")
            return intersecting_tiles
            
        except Exception as e:
            logger.error(f"Error finding intersecting tiles: {str(e)}")
            return []
    
    def _find_intersecting_tiles_s3(self, etrs89_polygon: gpd.GeoDataFrame) -> List[str]:
        """Find intersecting tiles using PostGIS spatial query"""
        try:
            # Convert polygon to WKT for PostGIS query
            polygon_wkt = etrs89_polygon.geometry.iloc[0].wkt
            logger.info(f"Querying PostGIS for polygon: {etrs89_polygon.total_bounds}")
            
            # Import database service
            from services.database import DatabaseService
            db_service = DatabaseService()
            
            # Single SQL query - lightning fast!
            query = """
            SELECT name, s3_path FROM lidarpt2m2025tiles 
            WHERE ST_Intersects(geometry, ST_GeomFromText(%s, 3763))
            """
            
            # Execute query
            results = db_service.execute_query(query, (polygon_wkt,))
            intersecting_tiles = [(row['name'], row['s3_path']) for row in results]
            
            logger.info(f"Found {len(intersecting_tiles)} intersecting tiles via PostGIS")
            
            # Get actual S3 file names by querying S3 bucket
            logger.info("Querying S3 bucket for actual file names...")
            
            s3_paths = []
            for tile_name, s3_path in intersecting_tiles:
                # Query S3 for files that start with the s3_path prefix
                try:
                    response = self.s3_client.list_objects_v2(
                        Bucket=self.s3_bucket,
                        Prefix=s3_path
                    )
                    
                    if 'Contents' in response and len(response['Contents']) > 0:
                        # Get the first matching file
                        actual_s3_path = response['Contents'][0]['Key']
                        s3_paths.append(actual_s3_path)
                        logger.info(f"Found S3 file: {actual_s3_path}")
                    else:
                        logger.warning(f"No S3 file found for tile {tile_name}")
                        
                except Exception as e:
                    logger.error(f"Error querying S3 for tile {tile_name}: {str(e)}")
            
            logger.info(f"Found {len(s3_paths)} actual S3 files")
            return s3_paths
            
        except Exception as e:
            logger.error(f"Error querying PostGIS: {str(e)}")
            return []
    
    def _tile_name_suggests_intersection(self, tile_name: str, polygon_bounds: Tuple[float, ...]) -> bool:
        """Simple heuristic to check if tile name suggests it might intersect with polygon"""
        try:
            # Extract coordinates from tile name (e.g., MDT-2m-205263-04-2024.tif)
            # This is a simple heuristic - in practice, you'd need to know the naming convention
            parts = tile_name.split('-')
            if len(parts) >= 3:
                # Try to extract numeric parts that might be coordinates
                for part in parts:
                    if part.isdigit() and len(part) >= 4:
                        # Simple heuristic: if tile number is in reasonable range
                        # This is a placeholder - real implementation would need proper coordinate mapping
                        return True
            return True  # Default to True for now - let intersection check handle it
        except:
            return True  # Default to True if parsing fails
    
    def _download_tile_from_s3(self, s3_key: str) -> Optional[str]:
        """Download a tile from S3 to local storage with intelligent caching"""
        try:
            # Use existing LidarPt directory for caching
            cache_dir = "/app/data/LidarPt"
            os.makedirs(cache_dir, exist_ok=True)
            
            local_filename = os.path.basename(s3_key)
            local_path = os.path.join(cache_dir, local_filename)
            
            # Check if file exists and is recent (7 days old)
            if os.path.exists(local_path):
                import time
                file_age = time.time() - os.path.getmtime(local_path)
                if file_age < 7 * 24 * 3600:  # 7 days
                    logger.info(f"Using cached tile: {local_path}")
                    return local_path
            
            # Download from S3
            logger.info(f"Downloading tile from S3: {s3_key}")
            self.s3_client.download_file(self.s3_bucket, s3_key, local_path)
            logger.info(f"Downloaded tile from S3: {s3_key} -> {local_path}")
            
            return local_path
            
        except Exception as e:
            logger.error(f"Error downloading tile from S3: {str(e)}")
            return None
    
    def _tile_intersects_polygon(self, tile_path: str, etrs89_polygon: gpd.GeoDataFrame) -> bool:
        """Check if a tile intersects with the polygon"""
        try:
            with rasterio.open(tile_path) as src:
                # Get tile bounds
                tile_bounds = src.bounds
                tile_box = gpd.GeoDataFrame([1], geometry=[box(tile_bounds.left, tile_bounds.bottom, 
                                                             tile_bounds.right, tile_bounds.top)], 
                                          crs=self.etrs89_crs)
                
                # Check intersection
                return etrs89_polygon.intersects(tile_box.geometry.iloc[0]).any()
                
        except Exception as e:
            logger.warning(f"Error checking tile intersection: {str(e)}")
            return False
    
    def _find_intersecting_tiles_local(self, etrs89_polygon: gpd.GeoDataFrame) -> List[str]:
        """Find intersecting tiles from local directory"""
        try:
            intersecting_tiles = []
            
            if not os.path.exists(self.lidar_directory):
                logger.error(f"LIDAR directory not found: {self.lidar_directory}")
                return []
            
            # Get all LIDAR tile files
            lidar_files = []
            for root, dirs, files in os.walk(self.lidar_directory):
                for file in files:
                    if file.lower().endswith(('.tif', '.tiff')):
                        lidar_files.append(os.path.join(root, file))
            
            logger.info(f"Found {len(lidar_files)} LIDAR tiles in directory")
            
            # Check each tile for intersection
            for tile_path in lidar_files:
                try:
                    with rasterio.open(tile_path) as src:
                        # Get tile bounds in EPSG:3763
                        tile_bounds = src.bounds
                        
                        # Simple bounds check first (faster)
                        if self._bounds_intersect(polygon_bounds, tile_bounds):
                            # More precise intersection check
                            if self._tile_intersects_polygon(src, etrs89_polygon):
                                intersecting_tiles.append(tile_path)
                                logger.info(f"Found intersecting tile: {os.path.basename(tile_path)}")
                
                except Exception as e:
                    logger.warning(f"Error checking tile {tile_path}: {str(e)}")
                    continue
            
            logger.info(f"Found {len(intersecting_tiles)} intersecting tiles")
            return intersecting_tiles
            
        except Exception as e:
            logger.error(f"Error finding intersecting tiles: {str(e)}")
            raise
    
    def _bounds_intersect(self, bounds1: Tuple[float, ...], bounds2: Tuple[float, ...]) -> bool:
        """Check if two bounding boxes intersect"""
        return not (bounds1[2] < bounds2[0] or bounds1[0] > bounds2[2] or 
                   bounds1[3] < bounds2[1] or bounds1[1] > bounds2[3])
    
    
    def _merge_lidar_tiles(self, tile_paths: List[str], polygon_id: str) -> str:
        """Merge multiple LIDAR tiles into single EPSG:3763 file"""
        try:
            # Create temporary file for merged tiles
            temp_dir = f"/tmp/lidar_merge_{polygon_id}"
            os.makedirs(temp_dir, exist_ok=True)
            merged_path = os.path.join(temp_dir, f"{polygon_id}_merged_etrs89.tif")
            
            logger.info(f"Merging {len(tile_paths)} LIDAR tiles to {merged_path}")
            
            # Use rasterio.merge to combine tiles
            merged_array, merged_transform = merge(tile_paths)
            
            # Get metadata from first tile
            with rasterio.open(tile_paths[0]) as src:
                merged_meta = src.meta.copy()
                merged_meta.update({
                    'driver': 'GTiff',
                    'height': merged_array.shape[1],
                    'width': merged_array.shape[2],
                    'transform': merged_transform,
                    'compress': 'lzw'
                })
            
            # Write merged file
            with rasterio.open(merged_path, 'w', **merged_meta) as dst:
                dst.write(merged_array)
            
            logger.info(f"Successfully merged LIDAR tiles to {merged_path}")
            return merged_path
            
        except Exception as e:
            logger.error(f"Error merging LIDAR tiles: {str(e)}")
            raise
    
    def _reproject_to_wgs84(self, etrs89_path: str, polygon_id: str) -> str:
        """Reproject merged LIDAR DEM from EPSG:3763 to WGS84"""
        try:
            # Create temporary file for WGS84 DEM
            temp_dir = f"/tmp/lidar_wgs84_{polygon_id}"
            os.makedirs(temp_dir, exist_ok=True)
            wgs84_path = os.path.join(temp_dir, f"{polygon_id}_wgs84.tif")
            
            logger.info(f"Reprojecting LIDAR DEM from EPSG:3763 to WGS84: {wgs84_path}")
            
            with rasterio.open(etrs89_path) as src:
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
            
            logger.info(f"Successfully reprojected LIDAR DEM to WGS84: {wgs84_path}")
            return wgs84_path
            
        except Exception as e:
            logger.error(f"Error reprojecting LIDAR DEM to WGS84: {str(e)}")
            raise
    
    def _clip_lidar_dem(self, wgs84_dem_path: str, polygon_geometry: Dict[str, Any], polygon_id: str) -> str:
        """Clip WGS84 LIDAR DEM with original WGS84 polygon"""
        try:
            # Create output directory
            output_dir = f"/app/data/polygon_sessions/{polygon_id}"
            os.makedirs(output_dir, exist_ok=True)
            
            clipped_path = os.path.join(output_dir, f"{polygon_id}_lidar.tif")
            
            logger.info(f"Clipping LIDAR DEM with WGS84 polygon: {clipped_path}")
            
            # Create polygon geometry
            polygon_geom = [shape(polygon_geometry['geometry'])]
            
            with rasterio.open(wgs84_dem_path) as src:
                # Clip the DEM with the polygon
                clipped_data, clipped_transform = mask(src, polygon_geom, crop=True, nodata=np.nan)
                
                # Update metadata
                clipped_meta = src.meta.copy()
                clipped_meta.update({
                    'height': clipped_data.shape[1],
                    'width': clipped_data.shape[2],
                    'transform': clipped_transform,
                    'nodata': np.nan,
                    'compress': 'lzw'
                })
                
                # Write clipped file
                with rasterio.open(clipped_path, 'w', **clipped_meta) as dst:
                    dst.write(clipped_data)
            
            logger.info(f"Successfully clipped LIDAR DEM: {clipped_path}")
            return clipped_path
            
        except Exception as e:
            logger.error(f"Error clipping LIDAR DEM: {str(e)}")
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
        temp_dirs = [f"/tmp/lidar_merge_{polygon_id}", f"/tmp/lidar_wgs84_{polygon_id}"]
        for temp_dir in temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Error cleaning up directory {temp_dir}: {str(e)}")


# Global LIDAR processor instance
lidar_processor = LidarProcessor()


def process_lidar_dem(polygon_geometry: Dict[str, Any], polygon_id: str) -> str:
    """
    Main function to process LIDAR DEM with CRS transformation
    
    Args:
        polygon_geometry: GeoJSON polygon in WGS84
        polygon_id: Unique polygon identifier
        
    Returns:
        Path to clipped WGS84 LIDAR DEM TIFF file
    """
    return lidar_processor.process_lidar_dem(polygon_geometry, polygon_id)
