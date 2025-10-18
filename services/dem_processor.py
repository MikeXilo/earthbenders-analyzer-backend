"""
Services for processing Digital Elevation Model (DEM) data from multiple sources
Supports SRTM, LIDAR PT, and LIDAR USA data sources with unified processing pipeline
"""
import os
import logging
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.merge import merge
from shapely.geometry import shape
from typing import Dict, List, Any, Optional
import base64
from io import BytesIO
from PIL import Image
import time

from config.dem_sources import get_dem_config, validate_dem_source

logger = logging.getLogger(__name__)

class DEMProcessingError(Exception):
    """Base exception for DEM processing errors"""
    pass

class SRTMError(DEMProcessingError):
    """SRTM-specific processing errors"""
    pass

class LIDARError(DEMProcessingError):
    """LIDAR-specific processing errors"""
    pass

class USGSError(DEMProcessingError):
    """USGS DEM-specific processing errors"""
    pass

class CRSInconsistencyError(DEMProcessingError):
    """CRS consistency validation errors"""
    pass

class DEMProcessor:
    """Unified DEM processing for multiple data sources"""
    
    def __init__(self):
        self.expected_crs = 'EPSG:4326'  # WGS84
    
    def process_dem_files(self, dem_files: List[str], geojson_data: Dict[str, Any], 
                        output_folder: str, data_source: str = 'srtm') -> Dict[str, Any]:
        """
        Process DEM files from any source (SRTM, LIDAR PT, LIDAR USA)
        
        Args:
            dem_files: List of DEM file paths
            geojson_data: GeoJSON polygon geometry **MUST BE IN WGS84 (EPSG:4326)**
            output_folder: Output directory for processed files
            data_source: Source type ('srtm', 'lidar', 'usgs-dem')
            
        Expected CRS by source:
            - SRTM: WGS84 (EPSG:4326) - native format
            - LIDAR PT: Reprojected to WGS84 before this function (ETRS89→WGS84)
            - USGS DEM: WGS84 (EPSG:4326) - requested from ArcGIS API in WGS84
            
        Returns:
            dict: Processed data including visualization and metadata
        """
        try:
            start_time = time.time()
            logger.info(f"Processing {data_source} DEM files: {dem_files}")
            
            # Validate data source
            if not validate_dem_source(data_source):
                raise DEMProcessingError(f"Unsupported data source: {data_source}")
            
            # Get configuration for this data source
            config = get_dem_config(data_source)
            logger.info(f"Using {data_source} configuration: {config['description']}")
            
            # Validate CRS consistency
            self._validate_crs_consistency(dem_files)
            
            # Route to source-specific processing
            if data_source == 'srtm':
                result = self._process_srtm_specific(dem_files, geojson_data, output_folder)
            elif data_source == 'lidar':
                result = self._process_lidar_specific(dem_files, geojson_data, output_folder)
            elif data_source == 'usgs-dem':
                result = self._process_usgs_specific(dem_files, geojson_data, output_folder)
            else:
                raise DEMProcessingError(f"Unknown data source: {data_source}")
            
            # Add performance metrics
            processing_time = time.time() - start_time
            logger.info(f"DEM processing completed in {processing_time:.2f}s for {data_source}")
            
            if result:
                result['processing_time'] = processing_time
                result['data_source'] = data_source
            
            return result
                
        except CRSInconsistencyError as e:
            logger.error(f"CRS validation failed: {str(e)}")
            raise
        except SRTMError as e:
            logger.error(f"SRTM processing failed: {str(e)}")
            raise
        except LIDARError as e:
            logger.error(f"LIDAR processing failed: {str(e)}")
            raise
        except USGSError as e:
            logger.error(f"USGS DEM processing failed: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in DEM processing: {str(e)}")
            raise DEMProcessingError(f"DEM processing failed: {str(e)}")
    
    def _validate_crs_consistency(self, dem_files: List[str], expected_crs: str = 'EPSG:4326'):
        """Ensure all DEM files have consistent CRS"""
        try:
            for file in dem_files:
                with rasterio.open(file) as src:
                    if src.crs and src.crs.to_epsg() != 4326:
                        logger.warning(f"File {file} has CRS {src.crs}, expected WGS84")
                        # Don't raise error, just log warning for now
        except Exception as e:
            logger.warning(f"Could not validate CRS for {file}: {str(e)}")
    
    def _process_srtm_specific(self, dem_files: List[str], geojson_data: Dict[str, Any], 
                             output_folder: str) -> Dict[str, Any]:
        """Process SRTM-specific DEM files"""
        try:
            logger.info("Processing SRTM-specific DEM files")
            return self._process_dem_generic(dem_files, geojson_data, output_folder, 'srtm')
        except Exception as e:
            raise SRTMError(f"SRTM processing failed: {str(e)}")
    
    def _process_lidar_specific(self, dem_files: List[str], geojson_data: Dict[str, Any], 
                              output_folder: str) -> Dict[str, Any]:
        """Process LIDAR-specific DEM files"""
        try:
            logger.info("Processing LIDAR-specific DEM files")
            return self._process_dem_generic(dem_files, geojson_data, output_folder, 'lidar')
        except Exception as e:
            raise LIDARError(f"LIDAR processing failed: {str(e)}")
    
    def _process_usgs_specific(self, dem_files: List[str], geojson_data: Dict[str, Any], 
                              output_folder: str) -> Dict[str, Any]:
        """Process USGS DEM-specific files"""
        try:
            logger.info("Processing USGS DEM-specific files")
            return self._process_dem_generic(dem_files, geojson_data, output_folder, 'usgs-dem')
        except Exception as e:
            raise USGSError(f"USGS DEM processing failed: {str(e)}")
    
    def _process_dem_generic(self, dem_files: List[str], geojson_data: Dict[str, Any], 
                           output_folder: str, data_source: str) -> Dict[str, Any]:
        """Generic DEM processing logic shared by all sources"""
        try:
            # Ensure output folder exists
            os.makedirs(output_folder, exist_ok=True)
            logger.info(f"Using output folder for {data_source} processing: {output_folder}")
            
            # Define paths for temporary files
            temp_mosaic_path = os.path.join(output_folder, "temp_mosaic.tif")
            clipped_dem_path = os.path.join(output_folder, "clipped_dem.tif")
            
            # Convert GeoJSON to shapely geometry
            polygon = shape(geojson_data['geometry'])
            clipping_polygon = polygon.buffer(0.0001)  # Small buffer to prevent edge issues
            
            logger.info(f"Clipping to exact polygon bounds: {polygon.bounds}")
            
            # Open DEM files and log their bounds
            src_files_to_mosaic = []
            for file in dem_files:
                try:
                    src = rasterio.open(file)
                    src_files_to_mosaic.append(src)
                    logger.info(f"{data_source} file {file} bounds: {src.bounds}")
                except Exception as e:
                    logger.error(f"Error opening {file}: {str(e)}")
                    raise
            
            if not src_files_to_mosaic:
                logger.error(f"No valid {data_source} files to process")
                return None
            
            # Create mosaic of all DEM tiles
            mosaic, out_trans = merge(src_files_to_mosaic)
            logger.info(f"Mosaic shape: {mosaic.shape}")
            
            # Save mosaic to temporary file
            with rasterio.open(temp_mosaic_path, 'w', driver='GTiff',
                            height=mosaic.shape[1], width=mosaic.shape[2],
                            count=1, dtype=mosaic.dtype,
                            crs=src_files_to_mosaic[0].crs,
                            transform=out_trans) as dst:
                dst.write(mosaic[0], 1)
            
            # Close source files
            for src in src_files_to_mosaic:
                src.close()
            
            # Mask to the exact polygon shape
            try:
                with rasterio.open(temp_mosaic_path) as src:
                    logger.info(f"Mosaic bounds: {src.bounds}")
                    geometries = [clipping_polygon]
                    
                    # Determine appropriate nodata value based on data type
                    if data_source == 'srtm':
                        # SRTM uses int16, so we need an integer nodata value
                        nodata_value = -32768  # Standard SRTM nodata value
                    else:
                        # For other sources, use np.nan if they're float
                        nodata_value = np.nan
                    
                    # Set crop=True to crop to the polygon bounds
                    # all_touched=True to include all pixels that touch the polygon
                    out_image, out_transform = mask(src, geometries, crop=True, all_touched=True, nodata=nodata_value)
                    
                    # For SRTM data, convert to float to handle nodata properly
                    if data_source == 'srtm':
                        # Convert to float32 to allow nan values for processing
                        out_image = out_image.astype(np.float32)
                        # Set masked values to nan for consistent processing
                        out_image = np.where(out_image == nodata_value, np.nan, out_image)
                    else:
                        # For other sources, set masked values to nan
                        out_image = np.where(out_image == 0, np.nan, out_image)
                    
                    # Update metadata
                    out_meta = src.meta.copy()
                    out_meta.update({
                        "driver": "GTiff",
                        "height": out_image.shape[1],
                        "width": out_image.shape[2],
                        "transform": out_transform,
                        "nodata": np.nan,  # Always use nan for output files
                        "dtype": 'float32',  # Ensure float32 for nan support
                        "compress": "lzw"
                    })
                    
                    # Write clipped file
                    with rasterio.open(clipped_dem_path, "w", **out_meta) as dest:
                        dest.write(out_image)
                    
                    logger.info(f"Successfully clipped {data_source} DEM: {clipped_dem_path}")
                    
                    # Generate visualization
                    visualization_data = self._generate_visualization(clipped_dem_path, data_source)
                    
                    # Calculate statistics
                    statistics = self._calculate_statistics(clipped_dem_path, data_source)
                    
                    return {
                        'clipped_dem_path': clipped_dem_path,
                        'bounds': {
                            'min_lon': float(polygon.bounds[0]),
                            'min_lat': float(polygon.bounds[1]),
                            'max_lon': float(polygon.bounds[2]),
                            'max_lat': float(polygon.bounds[3])
                        },
                        'image': visualization_data,
                        'statistics': statistics,
                        'data_source': data_source
                    }
                    
            except Exception as e:
                logger.error(f"Error in polygon masking: {str(e)}")
                raise
            finally:
                # Clean up temporary files
                if os.path.exists(temp_mosaic_path):
                    os.remove(temp_mosaic_path)
                    logger.debug(f"Cleaned up temporary mosaic: {temp_mosaic_path}")
                    
        except Exception as e:
            logger.error(f"Error in generic DEM processing: {str(e)}")
            raise
    
    def _generate_visualization(self, dem_path: str, data_source: str) -> str:
        """Generate base64 visualization for DEM data with proper color ramp and transparency"""
        try:
            with rasterio.open(dem_path) as src:
                # Read elevation data
                elevation_data = src.read(1)
                
                # Handle NoData values
                valid_data = elevation_data[~np.isnan(elevation_data)]
                if len(valid_data) == 0:
                    logger.warning(f"No valid data found in {data_source} file")
                    return ""
                
                # Normalize data for visualization
                min_elev = np.nanmin(valid_data)
                max_elev = np.nanmax(valid_data)
                
                # Create normalized array (0-1 range)
                normalized = np.where(
                    np.isnan(elevation_data), 
                    np.nan,  # Keep NoData as NaN for transparency
                    (elevation_data - min_elev) / (max_elev - min_elev)
                )
                
                # Apply color ramp (elevation-based colors)
                colored_image = self._apply_elevation_colormap(normalized)
                
                # Create RGBA image with transparency for NoData areas
                rgba_image = np.zeros((*normalized.shape, 4), dtype=np.uint8)
                
                # Set RGB values from colormap
                rgba_image[:, :, :3] = colored_image
                
                # Set alpha channel: 255 for valid data, 0 for NoData
                rgba_image[:, :, 3] = np.where(np.isnan(normalized), 0, 255)
                
                # Create PIL Image with RGBA mode for transparency
                img = Image.fromarray(rgba_image, mode='RGBA')
                
                # Convert to base64
                buffer = BytesIO()
                img.save(buffer, format='PNG')
                img_str = base64.b64encode(buffer.getvalue()).decode()
                
                logger.info(f"Generated visualization for {data_source} DEM with color ramp and transparency")
                return img_str
                
        except Exception as e:
            logger.error(f"Error generating visualization: {str(e)}")
            return ""
    
    def _apply_elevation_colormap(self, normalized_data: np.ndarray) -> np.ndarray:
        """Apply custom elevation color ramp for all data sources (SRTM, LIDAR PT, LIDAR US)"""
        # Create a 3D array for RGB values
        colored = np.zeros((*normalized_data.shape, 3), dtype=np.uint8)
        
        # Create mask for valid (non-NaN) data
        valid_mask = ~np.isnan(normalized_data)
        
        if not np.any(valid_mask):
            return colored
        
        # Get valid data
        valid_data = normalized_data[valid_mask]
        
        # Define the custom color ramp (49 colors + boundary colors)
        color_ramp = [
            (16, 105, 40),   # Boundary Color (elev_norm<0.0)
            (12, 130, 44),   # Ramp Color 1
            (8, 155, 48),    # Ramp Color 2
            (5, 181, 51),    # Ramp Color 3
            (5, 199, 59),    # Ramp Color 4
            (14, 203, 75),   # Ramp Color 5
            (22, 208, 91),   # Ramp Color 6
            (33, 212, 104),  # Ramp Color 7
            (50, 215, 108),  # Ramp Color 8
            (68, 219, 111),  # Ramp Color 9
            (86, 222, 114),  # Ramp Color 10
            (103, 225, 118), # Ramp Color 11
            (121, 228, 122), # Ramp Color 12
            (139, 231, 125), # Ramp Color 13
            (157, 234, 129), # Ramp Color 14
            (176, 238, 134), # Ramp Color 15
            (195, 242, 139), # Ramp Color 16
            (215, 246, 144), # Ramp Color 17
            (226, 245, 146), # Ramp Color 18
            (232, 240, 147), # Ramp Color 19
            (238, 235, 147), # Ramp Color 20
            (245, 229, 148), # Ramp Color 21
            (233, 216, 140), # Ramp Color 22
            (221, 202, 132), # Ramp Color 23
            (209, 188, 124), # Ramp Color 24
            (196, 173, 116), # Ramp Color 25
            (185, 157, 109), # Ramp Color 26
            (173, 141, 101), # Ramp Color 27
            (162, 125, 94),  # Ramp Color 28
            (156, 118, 91),  # Ramp Color 29
            (151, 110, 89),  # Ramp Color 30
            (146, 103, 86),  # Ramp Color 31
            (145, 101, 88),  # Ramp Color 32
            (150, 108, 97),  # Ramp Color 33
            (155, 115, 105), # Ramp Color 34
            (160, 123, 113), # Ramp Color 35
            (166, 131, 121), # Ramp Color 36
            (171, 138, 128), # Ramp Color 37
            (177, 146, 137), # Ramp Color 38
            (183, 153, 145), # Ramp Color 39
            (189, 161, 153), # Ramp Color 40
            (195, 169, 161), # Ramp Color 41
            (201, 176, 169), # Ramp Color 42
            (207, 184, 177), # Ramp Color 43
            (213, 192, 185), # Ramp Color 44
            (220, 200, 193), # Ramp Color 45
            (226, 207, 201), # Ramp Color 46
            (232, 215, 209), # Ramp Color 47
            (238, 223, 217), # Ramp Color 48
            (244, 231, 225), # Ramp Color 49
            (255, 255, 255) # Boundary Color (elev_norm≥1.0)
        ]
        
        # Convert to numpy array for efficient indexing
        color_ramp = np.array(color_ramp, dtype=np.uint8)
        
        # Handle boundary cases
        # Values < 0.0 get the first color
        low_mask = valid_data < 0.0
        colored[valid_mask][low_mask] = color_ramp[0]
        
        # Values >= 1.0 get the last color
        high_mask = valid_data >= 1.0
        colored[valid_mask][high_mask] = color_ramp[-1]
        
        # Values between 0.0 and 1.0 get interpolated colors
        mid_mask = (valid_data >= 0.0) & (valid_data < 1.0)
        if np.any(mid_mask):
            mid_data = valid_data[mid_mask]
            # Map 0.0-1.0 to 0-48 (49 ramp colors, excluding boundary colors)
            color_indices = (mid_data * 48).astype(int)
            # Ensure indices are within bounds
            color_indices = np.clip(color_indices, 0, 48)
            # Get colors (indices 1-49 in our array, since 0 is boundary color)
            colored[valid_mask][mid_mask] = color_ramp[color_indices + 1]
        
        return colored
    
    def _calculate_statistics(self, dem_path: str, data_source: str) -> Dict[str, Any]:
        """Calculate terrain statistics for DEM data"""
        try:
            with rasterio.open(dem_path) as src:
                elevation_data = src.read(1)
                valid_data = elevation_data[~np.isnan(elevation_data)]
                
                if len(valid_data) == 0:
                    return {
                        'elevation_min': None,
                        'elevation_max': None,
                        'elevation_mean': None,
                        'elevation_std': None,
                        'area_km2': 0
                    }
                
                # Calculate pixel area
                pixel_area = abs(src.transform[0] * src.transform[4])  # square degrees
                area_km2 = pixel_area * len(valid_data) * 111.32 * 111.32  # rough conversion
                
                return {
                    'elevation_min': float(np.min(valid_data)),
                    'elevation_max': float(np.max(valid_data)),
                    'elevation_mean': float(np.mean(valid_data)),
                    'elevation_std': float(np.std(valid_data)),
                    'area_km2': float(area_km2)
                }
                
        except Exception as e:
            logger.error(f"Error calculating statistics: {str(e)}")
            return {}


# Global DEM processor instance
dem_processor = DEMProcessor()


def process_dem_files(dem_files: List[str], geojson_data: Dict[str, Any], 
                     output_folder: str, data_source: str = 'srtm') -> Dict[str, Any]:
    """
    Main function to process DEM files from any source
    
    Args:
        dem_files: List of DEM file paths
        geojson_data: GeoJSON polygon geometry
        output_folder: Output directory for processed files
        data_source: Source type ('srtm', 'lidar', 'usgs-dem')
        
    Returns:
        dict: Processed data including visualization and metadata
    """
    return dem_processor.process_dem_files(dem_files, geojson_data, output_folder, data_source)


# Legacy compatibility - keep old function name for now
def process_srtm_files(srtm_files, geojson_data, output_folder=None):
    """
    Legacy function for backward compatibility
    Routes to new process_dem_files function
    """
    logger.warning("process_srtm_files() is deprecated. Use process_dem_files() instead.")
    return process_dem_files(srtm_files, geojson_data, output_folder, 'srtm')
