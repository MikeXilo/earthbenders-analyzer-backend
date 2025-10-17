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
from shapely.geometry import shape
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

logger = logging.getLogger(__name__)

class LidarProcessor:
    """Independent LIDAR DEM processing with CRS transformation"""
    
    def __init__(self, lidar_directory: str = "/app/data/LidarPt"):
        self.lidar_directory = lidar_directory
        self.wgs84_crs = CRS.from_epsg(4326)  # WGS84
        self.etrs89_crs = CRS.from_epsg(3763)  # ETRS89/TM06
        self._lock = threading.Lock()
    
    def process_lidar_dem(self, polygon_geometry: Dict[str, Any], polygon_id: str) -> Dict[str, Any]:
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
            
            # Step 3: Process tiles (merge if multiple)
            if len(intersecting_tiles) == 1:
                logger.info("Processing single LIDAR tile")
                merged_etrs89_path = intersecting_tiles[0]
            else:
                logger.info(f"Merging {len(intersecting_tiles)} LIDAR tiles")
                merged_etrs89_path = self._merge_lidar_tiles(intersecting_tiles, polygon_id)
            
            # Step 4: Reproject merged DEM to WGS84
            logger.info("Reprojecting merged LIDAR DEM to WGS84")
            wgs84_dem_path = self._reproject_to_wgs84(merged_etrs89_path, polygon_id)
            
            # Step 5: Clip with original WGS84 polygon
            logger.info("Clipping LIDAR DEM with original WGS84 polygon")
            clipped_lidar_path = self._clip_lidar_dem(wgs84_dem_path, polygon_geometry, polygon_id)
            
            # Step 6: Generate statistics and visualization
            logger.info("Generating LIDAR DEM statistics and visualization")
            bounds, statistics, image_data = self._generate_lidar_outputs(clipped_lidar_path)
            
            # Step 7: Cleanup temporary files
            self._cleanup_temp_files([merged_etrs89_path, wgs84_dem_path], polygon_id)
            
            logger.info(f"LIDAR DEM processing completed for polygon {polygon_id}")
            
            return {
                'clipped_srtm_path': clipped_lidar_path,  # Use same field name as SRTM for frontend compatibility
                'final_dem_path': clipped_lidar_path,     # Keep final_dem_path for database
                'bounds': bounds,
                'statistics': statistics,
                'image': image_data,
                'data_source': 'lidar',
                'status': 'completed'
            }
            
        except Exception as e:
            logger.error(f"Error processing LIDAR DEM for polygon {polygon_id}: {str(e)}")
            return {
                'error': str(e),
                'status': 'failed'
            }
    
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
            
            logger.info(f"Scanning LIDAR directory: {self.lidar_directory}")
            logger.info(f"Searching for tiles intersecting bounds: {polygon_bounds}")
            
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
    
    def _tile_intersects_polygon(self, tile_src: rasterio.DatasetReader, polygon_gdf: gpd.GeoDataFrame) -> bool:
        """Check if tile intersects with polygon using rasterio.mask"""
        try:
            # Get tile geometry
            tile_geom = [shape(polygon_gdf.geometry.iloc[0])]
            
            # Try to mask the tile with the polygon
            masked_data, _ = mask(tile_src, tile_geom, crop=True, nodata=np.nan)
            
            # Check if any valid data remains after masking
            return not np.all(np.isnan(masked_data))
            
        except Exception as e:
            logger.warning(f"Error checking tile intersection: {str(e)}")
            return False
    
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
    
    def _generate_lidar_outputs(self, clipped_lidar_path: str) -> Tuple[Dict[str, float], Dict[str, Any], str]:
        """Generate bounds, statistics, and visualization for clipped LIDAR DEM"""
        try:
            with rasterio.open(clipped_lidar_path) as src:
                # Get bounds
                bounds = {
                    'west': src.bounds.left,
                    'south': src.bounds.bottom,
                    'east': src.bounds.right,
                    'north': src.bounds.top
                }
                
                # Read data for statistics
                data = src.read(1)
                valid_data = data[~np.isnan(data)]
                
                if len(valid_data) == 0:
                    raise ValueError("No valid data in clipped LIDAR DEM")
                
                # Calculate statistics
                statistics = {
                    'min_elevation': float(np.min(valid_data)),
                    'max_elevation': float(np.max(valid_data)),
                    'mean_elevation': float(np.mean(valid_data)),
                    'std_elevation': float(np.std(valid_data)),
                    'pixel_count': len(valid_data),
                    'data_source': 'lidar'
                }
                
                # Generate visualization (base64 image)
                image_data = self._generate_lidar_visualization(data)
                
                logger.info(f"Generated LIDAR outputs - bounds: {bounds}, stats: {statistics}")
                return bounds, statistics, image_data
                
        except Exception as e:
            logger.error(f"Error generating LIDAR outputs: {str(e)}")
            raise
    
    def _generate_lidar_visualization(self, data: np.ndarray) -> str:
        """Generate base64 visualization for LIDAR DEM (same as SRTM approach)"""
        try:
            from PIL import Image
            import base64
            from io import BytesIO
            
            # Create masked array (same approach as SRTM)
            data_masked = np.ma.masked_where(np.isnan(data) | (data <= 0), data)
            
            # Normalize data to 0-1 range (same as SRTM)
            if not data_masked.mask.all():
                valid_data = data_masked[~data_masked.mask]
                if len(valid_data) > 0:
                    min_val, max_val = valid_data.min(), valid_data.max()
                    if max_val > min_val:
                        normalized_data = (data_masked - min_val) / (max_val - min_val)
                    else:
                        normalized_data = np.zeros_like(data_masked, dtype=np.float32)
                else:
                    normalized_data = np.zeros_like(data_masked, dtype=np.float32)
            else:
                normalized_data = np.zeros_like(data_masked, dtype=np.float32)
            
            # Create RGBA image with transparent background (same as SRTM)
            rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
            
            # Professional 15-level NCL topographic color scheme (same as SRTM)
            def get_topographic_color(elev_norm):
                """Get RGB color for normalized elevation (0-1) using continuous topographic ramp"""
                if elev_norm < 0.0:
                    return (16, 105, 40)      
                elif elev_norm < 0.07:
                    return (2, 198, 54)     
                elif elev_norm < 0.13:
                    return (30, 211, 104)     
                elif elev_norm < 0.20:
                    return (95, 224, 116)    
                elif elev_norm < 0.27:
                    return (161, 235, 130)     
                elif elev_norm < 0.33:
                    return (222, 248, 146)       
                elif elev_norm < 0.40:
                    return (245, 229, 148)    
                elif elev_norm < 0.47:
                    return (199, 177, 118)    
                elif elev_norm < 0.53:
                    return (162, 126, 94)    
                elif elev_norm < 0.60:
                    return (143, 98, 85)    
                elif elev_norm < 0.67:
                    return (162, 125, 116)    
                elif elev_norm < 0.73:
                    return (178, 150, 139)     
                elif elev_norm < 0.80:
                    return (199, 176, 170)      
                elif elev_norm < 0.87:
                    return (219, 205, 202)      
                elif elev_norm < 0.93:
                    return (237, 229, 227)      
                else:
                    return (255, 255, 255)  
            
            # Apply continuous color ramp (same logic as SRTM)
            for i in range(data.shape[0]):
                for j in range(data.shape[1]):
                    if not data_masked.mask[i, j]:  # Valid data point (same as SRTM)
                        elev_norm = normalized_data[i, j]
                        r, g, b = get_topographic_color(elev_norm)
                        
                        rgba[i, j, 0] = r  # Red
                        rgba[i, j, 1] = g  # Green
                        rgba[i, j, 2] = b  # Blue
                        rgba[i, j, 3] = 255  # Alpha (opaque)
                    else:
                        # Masked/invalid data - transparent (same as SRTM)
                        rgba[i, j, 3] = 0
            
            # Convert to PIL Image and upscale for higher resolution (same as SRTM)
            img = Image.fromarray(rgba)
            
            # Upscale the image for better quality (4x resolution for much sharper images)
            original_size = img.size
            upscaled_size = (original_size[0] * 4, original_size[1] * 4)
            img_upscaled = img.resize(upscaled_size, Image.Resampling.NEAREST)
            
            # Convert to base64
            buffer = BytesIO()
            img_upscaled.save(buffer, format='PNG')
            img_str = base64.b64encode(buffer.getvalue()).decode()
            
            return img_str
            
        except Exception as e:
            logger.error(f"Error generating LIDAR visualization: {str(e)}")
            return ""
    
    
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


def process_lidar_dem(polygon_geometry: Dict[str, Any], polygon_id: str) -> Dict[str, Any]:
    """
    Main function to process LIDAR DEM with CRS transformation
    
    Args:
        polygon_geometry: GeoJSON polygon in WGS84
        polygon_id: Unique polygon identifier
        
    Returns:
        Dict with LIDAR DEM processing results
    """
    return lidar_processor.process_lidar_dem(polygon_geometry, polygon_id)
