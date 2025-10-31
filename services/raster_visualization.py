"""
Raster visualization services for converting GeoTIFF files to color-mapped PNG images
"""
import os
import logging
import numpy as np
import rasterio
from PIL import Image
import base64
import io

logger = logging.getLogger(__name__)

def visualize_srtm(srtm_file_path, polygon_data=None):
    """
    Visualize SRTM elevation data as a colored image with elevation-based color mapping
    
    Args:
        srtm_file_path: Path to the SRTM raster file
        polygon_data: Optional GeoJSON polygon data for masking
        
    Returns:
        str: Base64 encoded PNG image
    """
    try:
        # Read the SRTM raster
        with rasterio.open(srtm_file_path) as src:
            elevation_data = src.read(1)
            bounds = src.bounds
            profile = src.profile
            
            # Handle nodata values from the original raster
            if src.nodata is not None:
                # Replace nodata values with NaN
                elevation_data = elevation_data.astype(np.float64)
                elevation_data[elevation_data == src.nodata] = np.nan
                logger.info(f"Converted {src.nodata} nodata values to NaN")
            
            # Also treat 0 values as nodata if they seem to be outside the polygon area
            # This is a common issue where 0 represents "no data" rather than sea level
            if np.any(elevation_data == 0):
                zero_count = np.sum(elevation_data == 0)
                total_pixels = elevation_data.size
                zero_percentage = (zero_count / total_pixels) * 100
                logger.info(f"Found {zero_count} zero values ({zero_percentage:.1f}% of total pixels)")
                
                # If more than 50% are zeros, treat them as nodata
                if zero_percentage > 50:
                    elevation_data[elevation_data == 0] = np.nan
                    logger.info("Treating zero values as nodata (likely outside polygon area)")
        
        # Mask using the polygon if available
        if polygon_data:
            try:
                from shapely.geometry import shape
                from rasterio.mask import mask
                
                # Convert GeoJSON to shapely geometry
                polygon = shape(polygon_data['geometry'])
                clipping_polygon = polygon.buffer(0.0001)  # Small buffer to avoid geometry issues
                
                # Create a rasterized mask of the polygon
                with rasterio.open(srtm_file_path) as src:
                    # Mask using the polygon - crop=False to keep original extent
                    masked_data, out_transform = mask(src, [clipping_polygon], crop=False, all_touched=False, nodata=np.nan)
                    masked_elevation = masked_data[0]  # Extract the data array
                
                # Replace the original elevation data with the masked version
                elevation_data = masked_elevation
                
                logger.info(f"Successfully masked SRTM to polygon shape")
                logger.info(f"Elevation data shape: {elevation_data.shape}")
                logger.info(f"Valid data points: {np.sum(~np.isnan(elevation_data))}")
                logger.info(f"Elevation range: {np.nanmin(elevation_data):.2f} to {np.nanmax(elevation_data):.2f}")
            except Exception as e:
                logger.warning(f"Failed to mask SRTM data: {str(e)}")
                # If masking fails, continue with the original data
        
        # Define elevation color scheme (green to brown to white for high elevations)
        # This creates a natural-looking elevation color map
        valid_data = elevation_data[~np.isnan(elevation_data)]
        logger.info(f"Valid data points for color mapping: {valid_data.size}")
        
        # Additional validation: filter out any remaining invalid values
        if valid_data.size > 0:
            # Remove any values that are still 0 (should have been converted to NaN)
            valid_data = valid_data[valid_data != 0]
            logger.info(f"Valid data points after removing zeros: {valid_data.size}")
        
        if valid_data.size == 0:
            # No valid data
            logger.warning("No valid elevation data found for color mapping")
            rgba = np.zeros((elevation_data.shape[0], elevation_data.shape[1], 4), dtype=np.uint8)
        else:
            elevation_min = np.min(valid_data)
            elevation_max = np.max(valid_data)
            elevation_range = elevation_max - elevation_min
            logger.info(f"Elevation range for color mapping: {elevation_min:.2f} to {elevation_max:.2f} (range: {elevation_range:.2f})")
            
            # Additional validation: check for reasonable elevation values
            if elevation_min < -1000 or elevation_max > 10000:
                logger.warning(f"Unusual elevation values detected: min={elevation_min:.2f}, max={elevation_max:.2f}")
                # Filter out extreme values that might be errors
                valid_mask = (elevation_data >= -1000) & (elevation_data <= 10000) & ~np.isnan(elevation_data)
                if np.any(valid_mask):
                    elevation_data = np.where(valid_mask, elevation_data, np.nan)
                    valid_data = elevation_data[~np.isnan(elevation_data)]
                    elevation_min = np.min(valid_data)
                    elevation_max = np.max(valid_data)
                    elevation_range = elevation_max - elevation_min
                    logger.info(f"Filtered elevation range: {elevation_min:.2f} to {elevation_max:.2f} (range: {elevation_range:.2f})")
            
            if elevation_range > 0:
                # Normalize elevation to 0-1
                normalized_elevation = (elevation_data - elevation_min) / elevation_range
                
                # Create RGBA array
                rgba = np.zeros((elevation_data.shape[0], elevation_data.shape[1], 4), dtype=np.uint8)
                
                # Apply elevation-based color mapping
                colored_pixels = 0
                for i in range(elevation_data.shape[0]):
                    for j in range(elevation_data.shape[1]):
                        # Only process valid elevation data (not NaN, not 0, within reasonable range)
                        if (not np.isnan(elevation_data[i, j]) and 
                            elevation_data[i, j] != 0 and 
                            -1000 <= elevation_data[i, j] <= 10000):
                            val = normalized_elevation[i, j]
                            
                            # Create elevation color scheme:
                            # Low elevation: green (0, 100, 0)
                            # Mid elevation: brown (139, 69, 19) 
                            # High elevation: white (255, 255, 255)
                            if val < 0.3:  # Low elevation - green
                                rgba[i, j, 0] = int(0 + val * 139 / 0.3)      # R: 0 to 139
                                rgba[i, j, 1] = int(100 + val * (69 - 100) / 0.3)  # G: 100 to 69
                                rgba[i, j, 2] = int(0 + val * 19 / 0.3)      # B: 0 to 19
                            elif val < 0.7:  # Mid elevation - brown
                                rgba[i, j, 0] = int(139 + (val - 0.3) * (255 - 139) / 0.4)  # R: 139 to 255
                                rgba[i, j, 1] = int(69 + (val - 0.3) * (255 - 69) / 0.4)     # G: 69 to 255
                                rgba[i, j, 2] = int(19 + (val - 0.3) * (255 - 19) / 0.4)    # B: 19 to 255
                            else:  # High elevation - white
                                rgba[i, j, 0] = 255  # R
                                rgba[i, j, 1] = 255   # G
                                rgba[i, j, 2] = 255   # B
                            
                            rgba[i, j, 3] = 255  # Alpha (fully opaque for valid data)
                            colored_pixels += 1
                        else:
                            rgba[i, j, 3] = 0  # Alpha (transparent for nodata)
                
                logger.info(f"Applied color mapping to {colored_pixels} pixels")
            else:
                # All elevations are the same
                rgba = np.zeros((elevation_data.shape[0], elevation_data.shape[1], 4), dtype=np.uint8)
                rgba[:, :, 0] = 0    # R
                rgba[:, :, 1] = 100  # G
                rgba[:, :, 2] = 0    # B
                rgba[:, :, 3] = 255  # Alpha
        
        # Convert to PIL Image and upscale for higher resolution
        img = Image.fromarray(rgba)
        
        # Upscale the image for better quality (4x resolution for much sharper images)
        original_size = img.size
        upscaled_size = (original_size[0] * 4, original_size[1] * 4)
        img_upscaled = img.resize(upscaled_size, Image.Resampling.NEAREST)
        
        buffered = io.BytesIO()
        img_upscaled.save(buffered, format="PNG", optimize=True)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        return img_str
        
    except Exception as e:
        logger.error(f"Error visualizing SRTM data: {str(e)}")
        raise

def process_raster_file(file_path, layer_type, polygon_data=None):
    """
    Process a raster file and return a Base64 PNG based on the layer type
    
    Args:
        file_path: Path to the raster file
        layer_type: Type of layer (srtm, slope, aspect, etc.)
        polygon_data: Optional polygon data for masking
        
    Returns:
        str: Base64 encoded PNG image
    """
    try:
        # Import visualization functions from terrain service
        from services.terrain import (
            visualize_slope, 
            visualize_aspect, 
            visualize_geomorphons, 
            visualize_hillshade, 
            visualize_drainage_network
        )
        
        # Map layer types to their visualization functions
        visualization_map = {
            'srtm': visualize_srtm,
            'slope': visualize_slope,
            'aspect': visualize_aspect,
            'geomorphons': visualize_geomorphons,
            'hillshade': visualize_hillshade,
            'drainage_network': visualize_drainage_network,
            'contours': None,  # Contours are GeoJSON files, not raster
        }
        
        # Get the appropriate visualization function
        processor_function = visualization_map.get(layer_type)
        
        if not processor_function:
            if layer_type == 'contours':
                # Contours are GeoJSON files, not raster files
                logger.info(f"Contours detected as GeoJSON file, not raster")
                return None
            else:
                raise ValueError(f"No visualization function found for layer type: {layer_type}")
        
        logger.info(f"Processing {layer_type} raster file: {file_path}")
        
        # Call the visualization function with polygon data
        result = processor_function(file_path, polygon_data)
        
        # Handle different return types from visualization functions
        if isinstance(result, dict) and 'image' in result:
            # Some functions return a dict with 'image' key
            return result['image']
        elif isinstance(result, str):
            # Some functions return the Base64 string directly
            return result
        else:
            raise ValueError(f"Unexpected return type from {layer_type} visualization function")
            
    except Exception as e:
        logger.error(f"Error processing {layer_type} raster file {file_path}: {str(e)}")
        raise

def detect_layer_type_from_path(file_path):
    """
    Detect the layer type from the file path using regex patterns
    
    Args:
        file_path: Path to the raster file
        
    Returns:
        str: Detected layer type or None if not found
    """
    import re
    import os
    
    # Get just the filename for easier matching
    filename = os.path.basename(file_path).lower()
    
    # Check for clipped_dem.tif or dem.tif first (these are elevation/SRTM files)
    if 'clipped_dem.tif' in filename or filename == 'dem.tif':
        return 'srtm'
    
    # Pattern to match layer types in filenames
    # e.g., '.../polygon_id_slope.tif' -> 'slope'
    # e.g., '.../polygon_id_drainage_network.tif' -> 'drainage_network'
    # e.g., '.../polygon_id_srtm.tif' -> 'srtm'
    pattern = r'_(srtm|slope|aspect|hillshade|geomorphons|drainage_network|contours|dem)\.tif'
    match = re.search(pattern, file_path)
    
    if match:
        layer_type = match.group(1)
        # Normalize 'dem' to 'srtm' since they're the same thing
        if layer_type == 'dem':
            return 'srtm'
        return layer_type
    
    return None
