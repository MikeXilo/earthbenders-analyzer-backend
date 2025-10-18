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
                            'west': float(polygon.bounds[0]),
                            'south': float(polygon.bounds[1]),
                            'east': float(polygon.bounds[2]),
                            'north': float(polygon.bounds[3])
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
                
                # DEBUG: Log data statistics
                logger.info(f"=== ELEVATION DATA DEBUG ===")
                logger.info(f"Total pixels: {elevation_data.size}")
                logger.info(f"Valid pixels: {len(valid_data)}")
                logger.info(f"NaN pixels: {np.sum(np.isnan(elevation_data))}")
                logger.info(f"Data type: {elevation_data.dtype}")
                logger.info(f"Raw data range: {np.nanmin(elevation_data)} to {np.nanmax(elevation_data)}")
                
                # Normalize data for visualization
                min_elev = np.nanmin(valid_data)
                max_elev = np.nanmax(valid_data)
                
                logger.info(f"Valid data range: {min_elev} to {max_elev}")
                logger.info(f"Elevation difference: {max_elev - min_elev}")
                
                # Check if all values are the same (flat terrain)
                if max_elev - min_elev == 0:
                    logger.warning(f"FLAT TERRAIN DETECTED: All elevation values are {min_elev}")
                    # For flat terrain, use a single color from the middle of the ramp
                    min_elev = min_elev - 1  # Create small range for visualization
                    max_elev = max_elev + 1
                
                # Create normalized array (0-1 range)
                normalized = np.where(
                    np.isnan(elevation_data), 
                    np.nan,  # Keep NoData as NaN for transparency
                    (elevation_data - min_elev) / (max_elev - min_elev)
                )
                
                # Apply color ramp (elevation-based colors)
                colored_image = self._apply_elevation_colormap(normalized)
                
                # DEBUG: Log color mapping results
                logger.info(f"=== COLOR MAPPING DEBUG ===")
                logger.info(f"Normalized range: {np.nanmin(normalized)} to {np.nanmax(normalized)}")
                logger.info(f"Colored image shape: {colored_image.shape}")
                logger.info(f"Colored image range: {colored_image.min()} to {colored_image.max()}")
                logger.info(f"Unique colors: {len(np.unique(colored_image.reshape(-1, colored_image.shape[-1]), axis=0))}")
                
                # Create RGBA image with transparency for NoData areas
                rgba_image = np.zeros((*normalized.shape, 4), dtype=np.uint8)
                
                # Set RGB values from colormap
                rgba_image[:, :, :3] = colored_image
                
                # ✅ CRITICAL: Set alpha ONLY where we have valid data
                alpha_mask = ~np.isnan(normalized)
                rgba_image[:, :, 3] = np.where(alpha_mask, 255, 0)
                
                # ✅ SAFETY: Ensure black pixels with alpha=0 are truly nodata
                # Don't confuse black elevation colors with nodata
                black_pixels = np.all(colored_image == 0, axis=2)
                valid_black = alpha_mask & black_pixels  # Black is valid if it's in alpha mask
                rgba_image[black_pixels & ~valid_black, 3] = 0  # Make invalid black transparent
                
                logger.info(f"Final RGBA: {np.sum(rgba_image[:,:,3] == 255)} opaque, {np.sum(rgba_image[:,:,3] == 0)} transparent")
                
                # DEBUG: Log final image stats
                logger.info(f"=== FINAL IMAGE DEBUG ===")
                logger.info(f"RGBA image shape: {rgba_image.shape}")
                logger.info(f"Alpha channel range: {rgba_image[:, :, 3].min()} to {rgba_image[:, :, 3].max()}")
                logger.info(f"Transparent pixels: {np.sum(rgba_image[:, :, 3] == 0)}")
                logger.info(f"Opaque pixels: {np.sum(rgba_image[:, :, 3] == 255)}")
                
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
        """Apply the exact 50-color elevation ramp with precise thresholds - VECTORIZED"""
        # Create a 3D array for RGB values initialized to transparent (will be handled by alpha channel)
        colored = np.zeros((*normalized_data.shape, 3), dtype=np.uint8)
        
        # Create mask for valid (non-NaN) data
        valid_mask = ~np.isnan(normalized_data)
        
        if not np.any(valid_mask):
            logger.warning("No valid data to colorize")
            return colored
        
        logger.info(f"Coloring {np.sum(valid_mask)} valid pixels out of {normalized_data.size} total")
        
        # Define color thresholds and RGB values
        # Format: (threshold, (R, G, B))
        color_stops = [
            (0.0,      (16, 105, 40)),
            (0.020408, (12, 130, 44)),
            (0.040816, (8, 155, 48)),
            (0.061224, (5, 181, 51)),
            (0.081633, (5, 199, 59)),
            (0.102041, (14, 203, 75)),
            (0.122449, (22, 208, 91)),
            (0.142857, (33, 212, 104)),
            (0.163265, (50, 215, 108)),
            (0.183673, (68, 219, 111)),
            (0.204082, (86, 222, 114)),
            (0.224490, (103, 225, 118)),
            (0.244898, (121, 228, 122)),
            (0.265306, (139, 231, 125)),
            (0.285714, (157, 234, 129)),
            (0.306122, (176, 238, 134)),
            (0.326531, (195, 242, 139)),
            (0.346939, (215, 246, 144)),
            (0.367347, (226, 245, 146)),
            (0.387755, (232, 240, 147)),
            (0.408163, (238, 235, 147)),
            (0.428571, (245, 229, 148)),
            (0.448980, (233, 216, 140)),
            (0.469388, (221, 202, 132)),
            (0.489796, (209, 188, 124)),
            (0.510204, (196, 173, 116)),
            (0.530612, (185, 157, 109)),
            (0.551020, (173, 141, 101)),
            (0.571429, (162, 125, 94)),
            (0.591837, (156, 118, 91)),
            (0.612245, (151, 110, 89)),
            (0.632653, (146, 103, 86)),
            (0.653061, (145, 101, 88)),
            (0.673469, (150, 108, 97)),
            (0.693878, (155, 115, 105)),
            (0.714286, (160, 123, 113)),
            (0.734694, (166, 131, 121)),
            (0.755102, (171, 138, 128)),
            (0.775510, (177, 146, 137)),
            (0.795918, (183, 153, 145)),
            (0.816327, (189, 161, 153)),
            (0.836735, (195, 169, 161)),
            (0.857143, (201, 176, 169)),
            (0.877551, (207, 184, 177)),
            (0.897959, (213, 192, 185)),
            (0.918367, (220, 200, 193)),
            (0.938776, (226, 207, 201)),
            (0.959184, (232, 215, 209)),
            (0.979592, (238, 223, 217)),
            (1.0,      (244, 231, 225)),
            (float('inf'), (255, 255, 255))  # Above 1.0
        ]
        
        # ✅ VECTORIZED COLOR ASSIGNMENT - Process all pixels at once
        for i in range(len(color_stops) - 1):
            threshold_low = color_stops[i][0]
            threshold_high = color_stops[i + 1][0]
            color = color_stops[i][1]  # ✅ Use the current threshold's color (not next!)
            
            # Create mask for pixels in this threshold range
            mask = valid_mask & (normalized_data >= threshold_low) & (normalized_data < threshold_high)
            
            # Assign color to all pixels in this range at once
            colored[mask, 0] = color[0]  # R
            colored[mask, 1] = color[1]  # G
            colored[mask, 2] = color[2]  # B
        
        # Handle edge case for exactly 1.0 and above
        exact_one_or_above = valid_mask & (normalized_data >= 1.0)
        if np.any(exact_one_or_above):
            colored[exact_one_or_above, 0] = 255
            colored[exact_one_or_above, 1] = 255
            colored[exact_one_or_above, 2] = 255
        
        logger.info(f"Color mapping complete. Non-zero pixels: {np.sum(np.any(colored > 0, axis=2))}")
        
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
