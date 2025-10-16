"""
Services for terrain analysis such as slope calculation
"""
import os
import logging
import numpy as np
import rasterio
from pathlib import Path
import base64
import io
from PIL import Image
from whitebox import WhiteboxTools

from utils.config import SAVE_DIRECTORY

logger = logging.getLogger(__name__)

# Initialize WhiteboxTools lazily to avoid worker conflicts
wbt = None

def get_whitebox_tools():
    """Get WhiteboxTools instance, initializing lazily to avoid worker conflicts"""
    global wbt
    if wbt is None:
        wbt = WhiteboxTools()
        wbt.verbose = False
    return wbt

def calculate_slopes(input_file_path, output_file_path):
    """
    Calculate slope from a DEM raster
    
    Args:
        input_file_path: Path to the input DEM file
        output_file_path: Path to the output slope file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Set the working directory for WhiteboxTools
        wbt = get_whitebox_tools()
        wbt.set_working_dir(os.path.dirname(output_file_path))
        
        # Calculate slope in percent (not degrees)
        logger.info(f"Calculating slope from {input_file_path} in percent...")
        wbt.slope(
            dem=str(input_file_path), 
            output=str(output_file_path), 
            units="percent"  # Percentage slope is more intuitive for users
        )
        
        if not os.path.exists(output_file_path):
            logger.error(f"Failed to calculate slope - output file not created")
            return False
            
        logger.info(f"Slope calculation complete: {output_file_path}")
        return True
    except Exception as e:
        logger.error(f"Error calculating slope: {str(e)}", exc_info=True)
        return False

def visualize_slope(slope_file_path, polygon_data=None):
    """
    Visualize slope data as a colored image with optional polygon masking
    
    Args:
        slope_file_path: Path to the slope raster file
        polygon_data: Optional GeoJSON polygon data for masking
        
    Returns:
        dict: Visualization data including base64 image and metadata
    """
    try:
        # Read the slope raster
        with rasterio.open(slope_file_path) as src:
            slope_data = src.read(1)
            bounds = src.bounds
            profile = src.profile
        
        # Mask using the polygon if available
        if polygon_data:
            try:
                from shapely.geometry import shape
                from rasterio.mask import mask
                
                # Convert GeoJSON to shapely geometry
                polygon = shape(polygon_data['geometry'])
                clipping_polygon = polygon.buffer(0.0001)  # Small buffer to avoid geometry issues
                
                # Create a rasterized mask of the polygon
                with rasterio.open(slope_file_path) as src:
                    # Mask using the polygon - crop=False to keep original extent
                    masked_data, out_transform = mask(src, [clipping_polygon], crop=False, all_touched=False, nodata=np.nan)
                    masked_slope = masked_data[0]  # Extract the data array
                
                # Replace the original slope data with the masked version
                slope_data = masked_slope
                
                logger.info(f"Successfully masked slope to polygon shape")
            except Exception as e:
                logger.error(f"Error masking slope with polygon: {str(e)}")
                # If masking fails, continue with the original data
        
        # Define slope percentage classes
        slope_classes = [
            (0, 3, [26, 150, 65]),     # Green
            (3, 5, [166, 217, 106]),   # Light green
            (5, 8, [255, 255, 191]),   # Yellow
            (8, 15, [253, 174, 97]),   # Light orange
            (15, 25, [215, 25, 28]),   # Red
            (25, 50, [128, 0, 38]),    # Dark red
            (50, float('inf'), [0, 0, 0])  # Black
        ]
        
        # Create a colormapped image with class-based colors
        # First create the colormap
        rgba = np.zeros((slope_data.shape[0], slope_data.shape[1], 4), dtype=np.uint8)
        
        # Initialize alpha to transparent everywhere
        rgba[:,:,3] = 0
        
        # Apply each class color where the slope falls within the class range
        for i, (min_slope, max_slope, color) in enumerate(slope_classes):
            mask = np.logical_and(slope_data >= min_slope, slope_data < max_slope)
            rgba[mask, 0] = color[0]  # R
            rgba[mask, 1] = color[1]  # G
            rgba[mask, 2] = color[2]  # B
            rgba[mask, 3] = 255       # Alpha (fully opaque for valid data)
        
        # Set alpha channel - transparent for NaN values
        rgba[np.isnan(slope_data), 3] = 0
        
        # Convert to PIL Image and upscale for higher resolution
        img = Image.fromarray(rgba)
        
        # Upscale the image for better quality (4x resolution for much sharper images)
        original_size = img.size
        upscaled_size = (original_size[0] * 4, original_size[1] * 4)
        img_upscaled = img.resize(upscaled_size, Image.Resampling.NEAREST)
        
        buffered = io.BytesIO()
        img_upscaled.save(buffered, format="PNG", optimize=True)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Calculate min/max for display
        valid_data = slope_data[~np.isnan(slope_data)]
        slope_min = np.min(valid_data) if valid_data.size > 0 else 0
        slope_max = np.max(valid_data) if valid_data.size > 0 else 100
        
        # Build the legend labels
        legend_labels = [f"{min_p}-{max_p if max_p != float('inf') else '+'}" for min_p, max_p, _ in slope_classes]
        
        return {
            'image': img_str,
            'min_slope': float(slope_min),
            'max_slope': float(slope_max),
            'width': upscaled_size[0],  # Use upscaled dimensions
            'height': upscaled_size[1],  # Use upscaled dimensions
            'bounds': {
                'north': bounds.top,
                'south': bounds.bottom,
                'east': bounds.right,
                'west': bounds.left
            },
            'slope_classes': legend_labels
        }
    except Exception as e:
        logger.error(f"Error visualizing slope: {str(e)}", exc_info=True)
        return None

def generate_contours(input_file_path, output_file_path, interval):
    """
    Generate contour lines from a DEM raster
    
    Args:
        input_file_path: Path to the input DEM file
        output_file_path: Path to the output contour GeoJSON file
        interval: Contour interval in meters
        
    Returns:
        dict: GeoJSON contour data if successful, None otherwise
    """
    try:
        import subprocess
        import json
        from pathlib import Path
        
        # Ensure output directory exists
        output_dir = os.path.dirname(output_file_path)
        os.makedirs(output_dir, exist_ok=True)
        
        # Get the base output path without extension for intermediate files
        output_base = str(output_file_path).replace('.geojson', '')
        
        # Output shapefile path
        output_shp = f"{output_base}.shp"
        
        logger.info(f"Generating contours from {input_file_path} with interval {interval}m using GDAL...")
        
        # Use the system-installed GDAL inside the Docker container
        gdal_contour_path = "gdal_contour"
        ogr2ogr_path = "ogr2ogr"
        
        logger.info(f"Using system gdal_contour and ogr2ogr commands inside Docker container")
        
        # Build the gdal_contour command
        cmd = [
            gdal_contour_path,
            "-a", "elevation",  # Name for the elevation attribute
            "-i", str(interval),  # Contour interval
            str(input_file_path),      # Input raster
            str(output_shp)       # Output shapefile
        ]
        
        # Run the command
        logger.info(f"Running command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        # Log the output for debugging
        if result.stdout:
            logger.info(f"GDAL stdout: {result.stdout}")
        if result.stderr:
            logger.warning(f"GDAL stderr: {result.stderr}")
        
        logger.info(f"GDAL command completed with return code: {result.returncode}")
        
        # Check if the shapefile was created
        if not os.path.exists(output_shp):
            logger.error(f"GDAL did not create the contour shapefile at {output_shp}")
            raise Exception(f"GDAL did not create the contour shapefile at {output_shp}")
        
        logger.info(f"Contour shapefile created successfully at {output_shp}")
        
        # Now convert shapefile to GeoJSON using ogr2ogr
        logger.info(f"Converting shapefile to GeoJSON using ogr2ogr...")
        
        # Build the ogr2ogr command
        ogr_cmd = [
            ogr2ogr_path,
            "-f", "GeoJSON",
            str(output_file_path),
            str(output_shp)
        ]
        
        # Run the ogr2ogr command
        logger.info(f"Running command: {' '.join(ogr_cmd)}")
        
        ogr_result = subprocess.run(ogr_cmd, check=True, capture_output=True, text=True)
        
        # Log the output for debugging
        if ogr_result.stdout:
            logger.info(f"OGR stdout: {ogr_result.stdout}")
        if ogr_result.stderr:
            logger.warning(f"OGR stderr: {ogr_result.stderr}")
        
        logger.info(f"OGR command completed with return code: {ogr_result.returncode}")
        
        # Check if the GeoJSON was created
        if not os.path.exists(output_file_path):
            logger.error(f"ogr2ogr did not create the GeoJSON file at {output_file_path}")
            raise Exception(f"ogr2ogr did not create the GeoJSON file at {output_file_path}")
        
        logger.info(f"GeoJSON file created successfully at {output_file_path}")
        
        # Load the GeoJSON file
        logger.info(f"Loading GeoJSON file content")
        with open(output_file_path, 'r') as f:
            contours_geojson = json.load(f)
                
        # Log some information about the contours
        feature_count = len(contours_geojson.get('features', []))
        logger.info(f"Generated {feature_count} contour features")
        
        if feature_count > 0:
            # Log the first feature's properties for debugging
            first_feature = contours_geojson['features'][0]
            logger.info(f"First contour feature properties: {first_feature.get('properties', {})}")
        else:
            logger.warning("No contour features were generated")
        
        # 🧹 CRITICAL CLEANUP: Delete intermediate Shapefile components to save storage
        logger.info("Cleaning up intermediate Shapefile files...")
        
        # Define the list of files to clean up based on the output base path
        shp_extensions = ['.shp', '.shx', '.dbf', '.prj', '.qpj', '.cpg']
        for ext in shp_extensions:
            temp_file_path = f"{output_base}{ext}"
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    logger.debug(f"✅ Removed temp file: {temp_file_path}")
                except Exception as cleanup_error:
                    logger.warning(f"⚠️ Failed to clean up {temp_file_path}: {cleanup_error}")
        
        # Return the contour GeoJSON
        logger.info("Contour generation completed successfully")
        return contours_geojson
    
    except Exception as e:
        logger.error(f"Error generating contours: {str(e)}", exc_info=True)
        return None

def calculate_geomorphons(input_file_path, output_file_path, search=50, threshold=0.0, forms=True):
    """
    Calculate geomorphons from a DEM raster using WhiteboxTools
    
    Args:
        input_file_path: Path to the input DEM file
        output_file_path: Path to the output geomorphons file
        search: Look up distance (in cells)
        threshold: Flatness threshold for the classification function (in degrees)
        forms: Classify geomorphons into 10 common land morphologies
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Set the working directory for WhiteboxTools
        wbt = get_whitebox_tools()
        wbt.set_working_dir(os.path.dirname(output_file_path))
        
        logger.info(f"Calculating geomorphons from {input_file_path}...")
        wbt = get_whitebox_tools()
        wbt.geomorphons(
            dem=str(input_file_path), 
            output=str(output_file_path),
            search=search,
            threshold=threshold,
            forms=forms
        )
        
        if not os.path.exists(output_file_path):
            logger.error(f"Failed to calculate geomorphons - output file not created")
            return False
            
        logger.info(f"Geomorphons calculation complete: {output_file_path}")
        return True
    except Exception as e:
        logger.error(f"Error calculating geomorphons: {str(e)}", exc_info=True)
        return False

def visualize_geomorphons(geomorphons_file_path, polygon_data=None):
    """
    Visualize geomorphons data as a colored image with optional polygon masking
    
    Args:
        geomorphons_file_path: Path to the geomorphons raster file
        polygon_data: Optional GeoJSON polygon data for masking
        
    Returns:
        dict: Visualization data including base64 image and metadata
    """
    try:
        # Read the geomorphons raster
        with rasterio.open(geomorphons_file_path) as src:
            geomorphons_data = src.read(1)
            bounds = src.bounds
            profile = src.profile
        
        # Mask using the polygon if available
        if polygon_data:
            try:
                from shapely.geometry import shape
                from rasterio.mask import mask
                
                # Convert GeoJSON to shapely geometry
                polygon = shape(polygon_data['geometry'])
                clipping_polygon = polygon.buffer(0.0001)  # Small buffer to avoid geometry issues
                
                # Create a rasterized mask of the polygon
                with rasterio.open(geomorphons_file_path) as src:
                    # Mask using the polygon - crop=False to keep original extent
                    # Use 0 as nodata value since Geomorphons are integer values (1-10), so 0 is safe
                    masked_data, out_transform = mask(src, [clipping_polygon], crop=False, all_touched=False, nodata=0)
                    masked_geomorphons = masked_data[0]  # Extract the data array
                
                # Replace the original geomorphons data with the masked version
                geomorphons_data = masked_geomorphons
                
                logger.info(f"Successfully masked geomorphons to polygon shape")
            except Exception as e:
                logger.error(f"Error masking geomorphons with polygon: {str(e)}")
                # If masking fails, continue with the original data
        
        # Define geomorphons landform types and their colors
        # Based on the QML symbology file provided
        landform_colors = {
            1: [113, 113, 113],  # Flat - #717171
            2: [83, 5, 14],      # Peak - #53050e
            3: [186, 34, 49],    # Ridge - #ba2231
            4: [212, 95, 32],    # Shoulder - #d45f20
            5: [229, 204, 91],   # Spur (convex) - #e5cc5b
            6: [233, 233, 152],  # Slope - #e9e998
            7: [166, 186, 98],   # Hollow (concave) - #a6ba62
            8: [17, 90, 21],     # Footslope - #115a15
            9: [105, 129, 149],  # Valley - #698195
            10: [0, 0, 0]        # Pit (depression) - #000000
        }
        
        # Create a colormapped image
        rgba = np.zeros((geomorphons_data.shape[0], geomorphons_data.shape[1], 4), dtype=np.uint8)
        
        # Initialize alpha to transparent everywhere
        rgba[:,:,3] = 0
        
        # Apply colors for each landform type
        for landform_type, color in landform_colors.items():
            mask = geomorphons_data == landform_type
            rgba[mask, 0] = color[0]  # R
            rgba[mask, 1] = color[1]  # G
            rgba[mask, 2] = color[2]  # B
            rgba[mask, 3] = 255       # Alpha (fully opaque for valid data)
        
        # Set alpha channel - transparent for NaN values
        rgba[np.isnan(geomorphons_data), 3] = 0
        
        # Convert to PIL Image and upscale for higher resolution
        img = Image.fromarray(rgba)
        
        # Upscale the image for better quality (4x resolution for much sharper images)
        original_size = img.size
        upscaled_size = (original_size[0] * 4, original_size[1] * 4)
        img_upscaled = img.resize(upscaled_size, Image.Resampling.NEAREST)
        
        buffered = io.BytesIO()
        img_upscaled.save(buffered, format="PNG", optimize=True)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Calculate min/max for display
        valid_data = geomorphons_data[~np.isnan(geomorphons_data)]
        geomorphons_min = np.min(valid_data) if valid_data.size > 0 else 1
        geomorphons_max = np.max(valid_data) if valid_data.size > 0 else 10
        
        # Build the legend labels
        landform_names = {
            1: "Flat",
            2: "Peak (summit)",
            3: "Ridge", 
            4: "Shoulder",
            5: "Spur (convex)",
            6: "Slope",
            7: "Hollow (concave)",
            8: "Footslope",
            9: "Valley",
            10: "Pit (depression)"
        }
        
        legend_labels = [landform_names.get(i, f"Type {i}") for i in range(1, 11)]
        
        return {
            'image': img_str,
            'min_geomorphons': float(geomorphons_min),
            'max_geomorphons': float(geomorphons_max),
            'width': upscaled_size[0],  # Use upscaled dimensions
            'height': upscaled_size[1],  # Use upscaled dimensions
            'bounds': {
                'north': bounds.top,
                'south': bounds.bottom,
                'east': bounds.right,
                'west': bounds.left
            },
            'landform_types': legend_labels
        }
    except Exception as e:
        logger.error(f"Error visualizing geomorphons: {str(e)}", exc_info=True)
        return None

def calculate_hypsometrically_tinted_hillshade(input_file_path, output_file_path, altitude=45.0, hs_weight=0.5, brightness=0.5, atmospheric=0.0, palette="atlas", zfactor=None):
    """
    Calculate hypsometrically tinted hillshade from a DEM raster using WhiteboxTools
    
    Args:
        input_file_path: Path to the input DEM file
        output_file_path: Path to the output hillshade file
        altitude: Illumination source altitude in degrees (0-90)
        hs_weight: Weight given to hillshade relative to relief (0.0-1.0)
        brightness: Brightness factor (0.0-1.0)
        atmospheric: Atmospheric effects weight (0.0-1.0)
        palette: Color palette options ('atlas', 'high_relief', 'arid', 'soft', 'muted', 'purple', 'viridis', 'gn_yl', 'pi_y_g', 'bl_yl_rd', 'deep')
        zfactor: Optional multiplier for when vertical and horizontal units are not the same
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Set the working directory for WhiteboxTools
        wbt = get_whitebox_tools()
        wbt.set_working_dir(os.path.dirname(output_file_path))
        
        logger.info(f"Calculating hypsometrically tinted hillshade from {input_file_path}...")
        wbt = get_whitebox_tools()
        wbt.hypsometrically_tinted_hillshade(
            dem=str(input_file_path), 
            output=str(output_file_path),
            altitude=altitude,
            hs_weight=hs_weight,
            brightness=brightness,
            atmospheric=atmospheric,
            palette=palette,
            zfactor=zfactor
        )
        
        if not os.path.exists(output_file_path):
            logger.error(f"Failed to calculate hillshade - output file not created")
            return False
            
        logger.info(f"Hypsometrically tinted hillshade calculation complete: {output_file_path}")
        return True
    except Exception as e:
        logger.error(f"Error calculating hypsometrically tinted hillshade: {str(e)}", exc_info=True)
        return False

def visualize_hillshade(hillshade_file_path, polygon_data=None):
    """
    Visualize hillshade data as a colored image with optional polygon masking
    
    Args:
        hillshade_file_path: Path to the hillshade raster file
        polygon_data: Optional GeoJSON polygon data for masking
        
    Returns:
        dict: Visualization data including base64 image and metadata
    """
    try:
        # Read the hillshade raster - hypsometrically tinted hillshade should be RGB
        with rasterio.open(hillshade_file_path) as src:
            # Read all bands for RGB data
            if src.count >= 3:
                hillshade_data = src.read()  # Read all bands
            else:
                hillshade_data = src.read(1)  # Single band fallback
            bounds = src.bounds
            profile = src.profile
        
        # Mask using the polygon if available
        if polygon_data:
            try:
                from shapely.geometry import shape
                from rasterio.mask import mask
                
                # Convert GeoJSON to shapely geometry
                polygon = shape(polygon_data['geometry'])
                clipping_polygon = polygon.buffer(0.0001)  # Small buffer to avoid geometry issues
                
                # Create a rasterized mask of the polygon
                with rasterio.open(hillshade_file_path) as src:
                    # Mask using the polygon - crop=False to keep original extent
                    masked_data, out_transform = mask(src, [clipping_polygon], crop=False, all_touched=False, nodata=np.nan)
                    
                    # Handle both single band and multi-band data
                    if len(masked_data.shape) == 3:
                        hillshade_data = masked_data  # Multi-band RGB data
                    else:
                        hillshade_data = masked_data[0]  # Single band data
                
                logger.info(f"Successfully masked hillshade to polygon shape")
            except Exception as e:
                logger.error(f"Error masking hillshade with polygon: {str(e)}")
                # If masking fails, continue with the original data
        
        # Handle the hypsometrically tinted hillshade RGB data properly
        if len(hillshade_data.shape) == 3 and hillshade_data.shape[0] >= 3:
            # Multi-band RGB data from hypsometrically tinted hillshade
            rgba = np.zeros((hillshade_data.shape[1], hillshade_data.shape[2], 4), dtype=np.uint8)
            rgba[:,:,0] = hillshade_data[0]  # R
            rgba[:,:,1] = hillshade_data[1]  # G
            rgba[:,:,2] = hillshade_data[2]  # B
            rgba[:,:,3] = 255  # Alpha
            
            # Handle nodata values properly - set alpha to 0 for nodata areas
            # Check for nodata values in any of the RGB bands
            nodata_mask = np.isnan(hillshade_data[0]) | np.isnan(hillshade_data[1]) | np.isnan(hillshade_data[2])
            rgba[nodata_mask, 3] = 0  # Make nodata areas transparent
            
            # Also handle pure black pixels (0,0,0) which WhiteboxTools often outputs for nodata
            black_mask = (rgba[:,:,0] == 0) & (rgba[:,:,1] == 0) & (rgba[:,:,2] == 0)
            rgba[black_mask, 3] = 0  # Make pure black pixels transparent
            
        elif len(hillshade_data.shape) == 2:
            # Single band data - this shouldn't happen with hypsometrically tinted hillshade
            # but handle it gracefully
            rgba = np.zeros((hillshade_data.shape[0], hillshade_data.shape[1], 4), dtype=np.uint8)
            rgba[:,:,0] = hillshade_data  # R
            rgba[:,:,1] = hillshade_data  # G  
            rgba[:,:,2] = hillshade_data  # B
            rgba[:,:,3] = 255  # Alpha
            
            # Handle nodata values
            rgba[np.isnan(hillshade_data), 3] = 0
            
            # Also handle pure black pixels (0,0,0) which WhiteboxTools often outputs for nodata
            black_mask = (rgba[:,:,0] == 0) & (rgba[:,:,1] == 0) & (rgba[:,:,2] == 0)
            rgba[black_mask, 3] = 0  # Make pure black pixels transparent
        else:
            # Fallback - shouldn't happen with proper hypsometrically tinted hillshade
            rgba = np.zeros((hillshade_data.shape[0], hillshade_data.shape[1], 4), dtype=np.uint8)
            rgba[:,:,0] = hillshade_data
            rgba[:,:,1] = hillshade_data
            rgba[:,:,2] = hillshade_data
            rgba[:,:,3] = 255
            rgba[np.isnan(hillshade_data), 3] = 0
            
            # Also handle pure black pixels (0,0,0) which WhiteboxTools often outputs for nodata
            black_mask = (rgba[:,:,0] == 0) & (rgba[:,:,1] == 0) & (rgba[:,:,2] == 0)
            rgba[black_mask, 3] = 0  # Make pure black pixels transparent
        
        # Convert to PIL Image and upscale for higher resolution
        img = Image.fromarray(rgba)
        
        # Upscale the image for better quality (4x resolution for much sharper images)
        original_size = img.size
        upscaled_size = (original_size[0] * 4, original_size[1] * 4)
        img_upscaled = img.resize(upscaled_size, Image.Resampling.NEAREST)
        
        buffered = io.BytesIO()
        img_upscaled.save(buffered, format="PNG", optimize=True)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Calculate min/max for display - handle both single and multi-band data
        if len(hillshade_data.shape) == 3:
            # Multi-band RGB data - use the first band for min/max calculation
            valid_data = hillshade_data[0][~np.isnan(hillshade_data[0])]
        else:
            # Single band data
            valid_data = hillshade_data[~np.isnan(hillshade_data)]
        
        hillshade_min = np.min(valid_data) if valid_data.size > 0 else 0
        hillshade_max = np.max(valid_data) if valid_data.size > 0 else 255
        
        return {
            'image': img_str,
            'min_hillshade': float(hillshade_min),
            'max_hillshade': float(hillshade_max),
            'width': upscaled_size[0],  # Use upscaled dimensions
            'height': upscaled_size[1],  # Use upscaled dimensions
            'bounds': {
                'north': bounds.top,
                'south': bounds.bottom,
                'east': bounds.right,
                'west': bounds.left
            }
        }
    except Exception as e:
        logger.error(f"Error visualizing hillshade: {str(e)}", exc_info=True)
        return None

def calculate_drainage_network(input_file_path, output_file_path):
    """
    Calculate drainage network using WhiteboxTools (fill depressions + D8 flow accumulation)
    
    Args:
        input_file_path: Path to the input DEM file
        output_file_path: Path to the output drainage network file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Set the working directory for WhiteboxTools
        wbt = get_whitebox_tools()
        wbt.set_working_dir(os.path.dirname(output_file_path))
        
        logger.info(f"Calculating drainage network from {input_file_path}...")
        
        # Step 1: Fill depressions to remove sinks
        filled_dem_path = os.path.join(os.path.dirname(output_file_path), "filled_dem.tif")
        wbt = get_whitebox_tools()
        wbt.fill_depressions(
            dem=str(input_file_path), 
            output=str(filled_dem_path)
        )
        
        if not os.path.exists(filled_dem_path):
            logger.error(f"Failed to fill depressions - intermediate file not created")
            return False
        
        # Step 2: Calculate D8 flow accumulation
        wbt = get_whitebox_tools()
        wbt.d8_flow_accumulation(
            i=str(filled_dem_path), 
            output=str(output_file_path)
        )
        
        # Clean up intermediate file
        try:
            os.remove(filled_dem_path)
        except:
            pass  # Ignore cleanup errors
        
        if not os.path.exists(output_file_path):
            logger.error(f"Failed to calculate drainage network - output file not created")
            return False
            
        logger.info(f"Drainage network calculation complete: {output_file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error calculating drainage network: {str(e)}", exc_info=True)
        return False

def calculate_aspect(input_file_path, output_file_path, convention="azimuth", gradient_alg="Horn", zero_for_flat=False):
    """
    Calculate aspect from a DEM raster using WhiteboxTools
    
    Args:
        input_file_path: Path to the input DEM file
        output_file_path: Path to the output aspect file
        convention: Convention for output angles ('azimuth' or 'trigonometric-angle')
        gradient_alg: Algorithm used to compute terrain gradient ('Horn' or 'ZevenbergenThorne')
        zero_for_flat: Whether to output zero for flat areas
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Set the working directory for WhiteboxTools
        wbt = get_whitebox_tools()
        wbt.set_working_dir(os.path.dirname(output_file_path))
        
        logger.info(f"Calculating aspect from {input_file_path}...")
        
        # Use WhiteboxTools aspect function
        wbt = get_whitebox_tools()
        wbt.aspect(
            dem=str(input_file_path), 
            output=str(output_file_path)
        )
        
        if not os.path.exists(output_file_path):
            logger.error(f"Failed to calculate aspect - output file not created")
            return False
            
        logger.info(f"Aspect calculation complete: {output_file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error calculating aspect: {str(e)}", exc_info=True)
        return False

def visualize_aspect(aspect_file_path, polygon_data=None):
    """
    Visualize aspect data as a colored image with optional polygon masking
    
    Args:
        aspect_file_path: Path to the aspect raster file
        polygon_data: Optional GeoJSON polygon data for masking
        
    Returns:
        dict: Visualization data including base64 image and metadata
    """
    try:
        # Read the aspect raster
        with rasterio.open(aspect_file_path) as src:
            aspect_data = src.read(1)
            bounds = src.bounds
            profile = src.profile
        
        # Mask using the polygon if available
        if polygon_data:
            try:
                from shapely.geometry import shape
                from rasterio.mask import mask
                
                # Convert GeoJSON to shapely geometry
                polygon = shape(polygon_data['geometry'])
                clipping_polygon = polygon.buffer(0.0001)  # Small buffer to avoid geometry issues
                
                # Create a rasterized mask of the polygon
                with rasterio.open(aspect_file_path) as src:
                    # Mask using the polygon - crop=False to keep original extent
                    masked_data, out_transform = mask(src, [clipping_polygon], crop=False, all_touched=False, nodata=np.nan)
                    masked_aspect = masked_data[0]  # Extract the data array
                
                # Replace the original aspect data with the masked version
                aspect_data = masked_aspect
                
                logger.info(f"Successfully masked aspect to polygon shape")
            except Exception as e:
                logger.error(f"Error masking aspect with polygon: {str(e)}")
                # If masking fails, continue with the original data
        
        # Create aspect color mapping using QGIS symbology colors
        # Based on the provided QML file with 8 directional categories
        aspect_colors = {
            'flat': [176, 176, 176],      # Flat (-1) - #b0b0b0
            'north': [255, 0, 0],          # North (0-22.5) - #ff0000
            'northeast': [255, 166, 0],    # Northeast (22.5-67.5) - #ffa600
            'east': [255, 255, 0],         # East (67.5-112.5) - #ffff00
            'southeast': [0, 255, 0],      # Southeast (112.5-157.5) - #00ff00
            'south': [0, 255, 255],        # South (157.5-202.5) - #00ffff
            'southwest': [0, 166, 255],    # Southwest (202.5-247.5) - #00a6ff
            'west': [0, 0, 255],           # West (247.5-292.5) - #0000ff
            'northwest': [255, 0, 255]     # Northwest (292.5-337.5) - #ff00ff
        }
        
        rgba = np.zeros((aspect_data.shape[0], aspect_data.shape[1], 4), dtype=np.uint8)
        
        # Initialize alpha to transparent everywhere
        rgba[:,:,3] = 0
        
        # Apply colors based on aspect direction
        for i in range(aspect_data.shape[0]):
            for j in range(aspect_data.shape[1]):
                if np.isnan(aspect_data[i, j]):
                    continue
                    
                aspect_val = aspect_data[i, j]
                
                # Determine direction and assign color
                if aspect_val < 0 or aspect_val == -9999:  # Flat areas
                    color = aspect_colors['flat']
                elif aspect_val <= 22.5 or aspect_val >= 337.5:  # North
                    color = aspect_colors['north']
                elif aspect_val <= 67.5:  # Northeast
                    color = aspect_colors['northeast']
                elif aspect_val <= 112.5:  # East
                    color = aspect_colors['east']
                elif aspect_val <= 157.5:  # Southeast
                    color = aspect_colors['southeast']
                elif aspect_val <= 202.5:  # South
                    color = aspect_colors['south']
                elif aspect_val <= 247.5:  # Southwest
                    color = aspect_colors['southwest']
                elif aspect_val <= 292.5:  # West
                    color = aspect_colors['west']
                else:  # Northwest
                    color = aspect_colors['northwest']
                
                rgba[i, j, 0] = color[0]  # R
                rgba[i, j, 1] = color[1]  # G
                rgba[i, j, 2] = color[2]  # B
                rgba[i, j, 3] = 255       # Alpha
        
        # Set alpha channel - transparent for NaN values
        rgba[np.isnan(aspect_data), 3] = 0
        
        # Convert to PIL Image and upscale for higher resolution
        img = Image.fromarray(rgba)
        
        # Upscale the image for better quality (4x resolution for much sharper images)
        original_size = img.size
        upscaled_size = (original_size[0] * 4, original_size[1] * 4)
        img_upscaled = img.resize(upscaled_size, Image.Resampling.NEAREST)
        
        buffered = io.BytesIO()
        img_upscaled.save(buffered, format="PNG", optimize=True)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Calculate min/max for display
        valid_data = aspect_data[~np.isnan(aspect_data)]
        aspect_min = np.min(valid_data) if valid_data.size > 0 else 0
        aspect_max = np.max(valid_data) if valid_data.size > 0 else 360
        
        return {
            'image': img_str,
            'min_aspect': float(aspect_min),
            'max_aspect': float(aspect_max),
            'width': upscaled_size[0],  # Use upscaled dimensions
            'height': upscaled_size[1],  # Use upscaled dimensions
            'bounds': {
                'north': bounds.top,
                'south': bounds.bottom,
                'east': bounds.right,
                'west': bounds.left
            }
        }
    except Exception as e:
        logger.error(f"Error visualizing aspect: {str(e)}", exc_info=True)
        return None

def visualize_drainage_network(drainage_file_path, polygon_data=None):
    """
    Visualize drainage network data as a colored image with optional polygon masking
    
    Args:
        drainage_file_path: Path to the drainage network raster file
        polygon_data: Optional GeoJSON polygon data for masking
        
    Returns:
        dict: Visualization data including base64 image and metadata
    """
    try:
        # Read the drainage network raster
        with rasterio.open(drainage_file_path) as src:
            drainage_data = src.read(1)
            bounds = src.bounds
            profile = src.profile
        
        # Mask using the polygon if available
        if polygon_data:
            try:
                from shapely.geometry import shape
                from rasterio.mask import mask
                
                # Convert GeoJSON to shapely geometry
                polygon = shape(polygon_data['geometry'])
                clipping_polygon = polygon.buffer(0.0001)  # Small buffer to avoid geometry issues
                
                # Create a rasterized mask of the polygon
                with rasterio.open(drainage_file_path) as src:
                    # Mask using the polygon - crop=False to keep original extent
                    masked_data, out_transform = mask(src, [clipping_polygon], crop=False, all_touched=False, nodata=np.nan)
                    
                    # Handle both single band and multi-band data
                    if len(masked_data.shape) == 3:
                        drainage_data = masked_data  # Multi-band data
                    else:
                        drainage_data = masked_data[0]  # Single band data
                
                logger.info(f"Successfully masked drainage network to polygon shape")
            except Exception as e:
                logger.error(f"Error masking drainage network with polygon: {str(e)}")
                # If masking fails, continue with the original data
        
        # Ensure drainage_data is 2D
        if len(drainage_data.shape) > 2:
            drainage_data = drainage_data[0]  # Take first band if multi-dimensional
        
        # Create drainage network color mapping
        # Use a blue color scheme for flow accumulation
        rgba = np.zeros((drainage_data.shape[0], drainage_data.shape[1], 4), dtype=np.uint8)
        
        # Handle nodata values
        valid_mask = ~np.isnan(drainage_data) & (drainage_data > 0)
        
        if np.any(valid_mask):
            # Get valid data for color mapping
            valid_data = drainage_data[valid_mask]
            
            # Use logarithmic scaling for better visualization
            log_data = np.log1p(valid_data)  # log(1 + x) to handle zeros
            log_min = np.min(log_data)
            log_max = np.max(log_data)
            
            if log_max > log_min:
                # Normalize to 0-1
                normalized = (log_data - log_min) / (log_max - log_min)
                
                # Create a normalized array for the full raster
                normalized_full = np.zeros_like(drainage_data, dtype=np.float32)
                normalized_full[valid_mask] = normalized
                
                # Apply blue color scheme (light blue to dark blue)
                for i in range(drainage_data.shape[0]):
                    for j in range(drainage_data.shape[1]):
                        if valid_mask[i, j]:
                            val = normalized_full[i, j]
                            # Blue color scheme: light blue (low) to dark blue (high)
                            rgba[i, j, 0] = int(255 * (1 - val * 0.7))  # R: 255 to 77
                            rgba[i, j, 1] = int(255 * (1 - val * 0.5))  # G: 255 to 128
                            rgba[i, j, 2] = 255  # B: always 255 (blue)
                            rgba[i, j, 3] = 255  # Alpha: opaque
                        else:
                            rgba[i, j, 3] = 0  # Alpha: transparent for nodata
            else:
                # All values are the same
                rgba[valid_mask, 0] = 77   # R
                rgba[valid_mask, 1] = 128 # G
                rgba[valid_mask, 2] = 255  # B
                rgba[valid_mask, 3] = 255  # Alpha
        else:
            # No valid data
            rgba[:, :, 3] = 0  # All transparent
        
        # Convert to PIL Image and upscale for higher resolution
        img = Image.fromarray(rgba)
        
        # Upscale the image for better quality (4x resolution for much sharper images)
        original_size = img.size
        upscaled_size = (original_size[0] * 4, original_size[1] * 4)
        img_upscaled = img.resize(upscaled_size, Image.Resampling.NEAREST)
        
        buffered = io.BytesIO()
        img_upscaled.save(buffered, format="PNG", optimize=True)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Calculate min/max for display
        if np.any(valid_mask):
            drainage_min = np.min(drainage_data[valid_mask])
            drainage_max = np.max(drainage_data[valid_mask])
        else:
            drainage_min = 0
            drainage_max = 1
        
        return {
            'image': img_str,
            'min_drainage': float(drainage_min),
            'max_drainage': float(drainage_max),
            'width': upscaled_size[0],  # Use upscaled dimensions
            'height': upscaled_size[1],  # Use upscaled dimensions
            'bounds': {
                'north': bounds.top,
                'south': bounds.bottom,
                'east': bounds.right,
                'west': bounds.left
            }
        }
    except Exception as e:
        logger.error(f"Error visualizing drainage network: {str(e)}", exc_info=True)
        return None

def calculate_centroid(points):
    """
    Calculate the centroid of a set of points forming a polygon
    
    Args:
        points: List of [lon, lat] coordinates
        
    Returns:
        list: [lon, lat] centroid coordinates
    """
    try:
        if not points or len(points) < 3:
            logger.error("Not enough points to calculate centroid")
            return None
        
        # Calculate centroid using the "shoelace formula"
        # First convert to a Shapely polygon and use its centroid property
        from shapely.geometry import Polygon
        
        # Handle case where the first and last points are the same (closed polygon)
        if points[0] == points[-1] and len(points) > 3:
            points = points[:-1]  # Remove the last point

        polygon = Polygon(points)
        centroid = [polygon.centroid.x, polygon.centroid.y]
        
        logger.info(f"Calculated centroid: {centroid}")
        
        return centroid
    except Exception as e:
        logger.exception("Error in calculate_centroid")
        return None 