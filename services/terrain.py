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

# Initialize WhiteboxTools
wbt = WhiteboxTools()
wbt.verbose = False

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
        img_upscaled = img.resize(upscaled_size, Image.Resampling.LANCZOS)
        
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
        wbt.set_working_dir(os.path.dirname(output_file_path))
        
        logger.info(f"Calculating geomorphons from {input_file_path}...")
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
                    masked_data, out_transform = mask(src, [clipping_polygon], crop=False, all_touched=False, nodata=np.nan)
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
        img_upscaled = img.resize(upscaled_size, Image.Resampling.LANCZOS)
        
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