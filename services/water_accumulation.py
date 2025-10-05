#!/usr/bin/env python3
"""
Water Accumulation Processing Service using GRASS

This service provides functions for calculating water accumulation (flow accumulation)
using GRASS r.watershed algorithm.
"""

import sys
import os
import logging
import tempfile
import base64
from pathlib import Path
import json
import numpy as np
from PIL import Image
import io
import subprocess
import shutil

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# GRASS GIS configuration
GRASS_BIN = 'grass78'  # Use GRASS 7.8
GRASS_PATH = '/usr/lib/grass78'

def calculate_water_accumulation(dem_file_path, polygon_id=None):
    """
    Calculate water accumulation using GRASS r.watershed
    
    Args:
        dem_file_path: Path to the input DEM file
        polygon_id: Optional polygon ID for storage/retrieval
        
    Returns:
        dict: Result dictionary with paths and metadata
    """
    logger.info(f"Processing water accumulation for DEM: {dem_file_path}")
    
    try:
        import rasterio
        import numpy as np
        import matplotlib.pyplot as plt
        
        # Create output directories
        output_dir = Path('/app/data')
        if polygon_id:
            output_dir = output_dir / f"polygon_sessions/{polygon_id}"
        else:
            output_dir = output_dir / "water_accumulation_temp"
            
        os.makedirs(output_dir, exist_ok=True)
        
        # Set output paths
        accumulation_path = str(output_dir / "flow_accumulation.tif")
        streams_path = str(output_dir / "streams.tif")
        
        # Create temporary directory for GRASS
        with tempfile.TemporaryDirectory() as temp_dir:
            # Set up environment variables for GRASS
            my_env = os.environ.copy()
            my_env['GISBASE'] = GRASS_PATH
            my_env['PATH'] = f"{my_env['PATH']}:{GRASS_PATH}/bin:{GRASS_PATH}/scripts"
            
            # Get DEM info with rasterio
            with rasterio.open(dem_file_path) as dem_src:
                dem_bounds = dem_src.bounds
                dem_crs = dem_src.crs
                
            # Create GRASS directory structure
            grass_db = Path(temp_dir) / "grassdata"
            location = "temp_location"
            mapset = "PERMANENT"
            
            os.makedirs(grass_db / location / mapset, exist_ok=True)
            
            # Determine creation parameters based on CRS
            logger.info(f"Creating GRASS database in {grass_db}")
            create_location_cmd = []
            
            # Use XY location for simplicity
            logger.info("Creating XY location")
            create_location_cmd = [
                GRASS_BIN, "-c", "XY", str(grass_db / location)
            ]
            
            # Create location
            try:
                logger.info(f"Executing: {' '.join(create_location_cmd)}")
                result = subprocess.run(create_location_cmd, env=my_env, 
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, check=True)
                logger.info(f"Location creation output: {result.stdout}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Error creating location: {e.stderr}")
                raise RuntimeError(f"Failed to create GRASS location: {e.stderr}")
            
            # Copy DEM to a location where GRASS can access it
            dem_copy_path = Path(temp_dir) / "dem.tif"
            shutil.copy2(dem_file_path, dem_copy_path)
            
            # Import DEM into GRASS
            logger.info(f"Importing DEM into GRASS: {dem_copy_path}")
            import_cmd = [
                GRASS_BIN, str(grass_db / location / mapset), "--exec", 
                "r.in.gdal", f"input={dem_copy_path}", "output=input_dem"
            ]
            
            try:
                logger.info(f"Executing: {' '.join(import_cmd)}")
                subprocess.run(import_cmd, env=my_env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                logger.error(f"Error importing DEM: {e.stderr.decode() if hasattr(e.stderr, 'decode') else e.stderr}")
                raise RuntimeError(f"Failed to import DEM into GRASS: {str(e)}")
            
            # Set region
            logger.info("Setting computational region")
            region_cmd = [
                GRASS_BIN, str(grass_db / location / mapset), "--exec",
                "g.region", "raster=input_dem"
            ]
            
            try:
                subprocess.run(region_cmd, env=my_env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                logger.error(f"Error setting region: {e.stderr.decode() if hasattr(e.stderr, 'decode') else e.stderr}")
                raise RuntimeError(f"Failed to set region in GRASS: {str(e)}")
            
            # Run r.watershed
            logger.info("Running r.watershed to calculate flow accumulation")
            watershed_cmd = [
                GRASS_BIN, str(grass_db / location / mapset), "--exec",
                "r.watershed", "elevation=input_dem", "accumulation=flow_accum",
                "stream=stream_rast", "threshold=100", "-a"
            ]
            
            try:
                subprocess.run(watershed_cmd, env=my_env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                logger.error(f"Error running r.watershed: {e.stderr.decode() if hasattr(e.stderr, 'decode') else e.stderr}")
                raise RuntimeError(f"Failed to run r.watershed: {str(e)}")
            
            # Export accumulation result
            logger.info(f"Exporting flow accumulation to: {accumulation_path}")
            export_accum_cmd = [
                GRASS_BIN, str(grass_db / location / mapset), "--exec",
                "r.out.gdal", "input=flow_accum", f"output={accumulation_path}",
                "format=GTiff"
            ]
            
            try:
                subprocess.run(export_accum_cmd, env=my_env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                logger.error(f"Error exporting accumulation: {e.stderr.decode() if hasattr(e.stderr, 'decode') else e.stderr}")
                raise RuntimeError(f"Failed to export accumulation: {str(e)}")
            
            # Export streams result
            logger.info(f"Exporting streams to: {streams_path}")
            export_stream_cmd = [
                GRASS_BIN, str(grass_db / location / mapset), "--exec",
                "r.out.gdal", "input=stream_rast", f"output={streams_path}",
                "format=GTiff"
            ]
            
            try:
                subprocess.run(export_stream_cmd, env=my_env, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                logger.error(f"Error exporting streams: {e.stderr.decode() if hasattr(e.stderr, 'decode') else e.stderr}")
                raise RuntimeError(f"Failed to export streams: {str(e)}")
        
        # Check if files were created
        if not os.path.exists(accumulation_path) or not os.path.exists(streams_path):
            raise RuntimeError("GRASS r.watershed did not produce expected output files")
            
        logger.info(f"GRASS processing complete. Accumulation: {accumulation_path}, Streams: {streams_path}")
        
        # Create visualizations from the GRASS output
        # Read the flow accumulation raster
        with rasterio.open(accumulation_path) as src:
            accumulation_data = src.read(1)
            bounds = src.bounds
            
            # Create a logarithmic color scale for better visualization
            accumulation_data = np.ma.masked_where(accumulation_data <= 0, accumulation_data)
            
            # Visualize flow accumulation
            plt.figure(figsize=(10, 10))
            plt.imshow(accumulation_data, cmap='Blues')
            plt.axis('off')
            plt.tight_layout(pad=0)
            
            # Save to BytesIO
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0, transparent=True)
            plt.close()
            
            # Convert to base64
            buf.seek(0)
            img_str = base64.b64encode(buf.getvalue()).decode()
            logger.info("Created water accumulation visualization")
        
        # Read the streams raster
        with rasterio.open(streams_path) as src:
            streams_data = src.read(1)
            
            # Visualize streams
            plt.figure(figsize=(10, 10))
            plt.imshow(streams_data > 0, cmap='Blues')
            plt.axis('off')
            plt.tight_layout(pad=0)
            
            # Save to BytesIO
            stream_buf = io.BytesIO()
            plt.savefig(stream_buf, format='png', bbox_inches='tight', pad_inches=0, transparent=True)
            plt.close()
            
            # Convert to base64
            stream_buf.seek(0)
            stream_img_str = base64.b64encode(stream_buf.getvalue()).decode()
            logger.info("Created stream network visualization")
        
        # Prepare the result
        result = {
            'water_accumulation': img_str,
            'streams': stream_img_str,
            'accumulation_path': accumulation_path,
            'streams_path': streams_path,
            'bounds': {
                'north': bounds.top,
                'south': bounds.bottom,
                'east': bounds.right,
                'west': bounds.left
            }
        }
        
        logger.info("Water accumulation processing completed successfully")
        return result
    
    except Exception as e:
        logger.error(f"Error in water accumulation processing: {str(e)}", exc_info=True)
        # Return a minimal result with error information
        return {
            'water_accumulation': "",
            'streams': "",
            'error': str(e),
            'bounds': {
                'north': 0,
                'south': 0,
                'east': 0,
                'west': 0
            }
        }


if __name__ == "__main__":
    # This allows testing the module directly
    if len(sys.argv) > 1:
        dem_file = sys.argv[1]
        polygon_id = sys.argv[2] if len(sys.argv) > 2 else None
        result = calculate_water_accumulation(dem_file, polygon_id)
        print(f"Processing completed. Results: {list(result.keys())}")
    else:
        print("Usage: python water_accumulation.py <dem_file_path> [polygon_id]") 