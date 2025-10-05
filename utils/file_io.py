"""
File I/O utilities for handling GeoJSON, raster files, and other data
"""
import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def save_geojson(data, filename, directory, polygon_id=None):
    """
    Save GeoJSON data to a file
    
    Args:
        data: The GeoJSON data to save
        filename: The filename to save to
        directory: The directory to save in
        polygon_id: Optional polygon ID to use as the folder name
        
    Returns:
        str: The full path to the saved file
    """
    try:
        # Extract polygon_id from the filename if not provided
        if polygon_id is None:
            # Remove file extension to get polygon_id
            polygon_id = os.path.splitext(filename)[0]
        
        # Create a subfolder with the polygon_id
        polygon_folder = os.path.join(directory, "polygon_sessions", polygon_id)
        os.makedirs(polygon_folder, exist_ok=True)
        
        # Full path to the file
        file_path = os.path.join(polygon_folder, filename)
        logger.info(f"Saving GeoJSON to: {file_path}")
        
        with open(file_path, 'w') as geojson_file:
            json.dump(data, geojson_file)
        
        logger.info(f"GeoJSON saved to: {file_path}")
        return file_path
    except Exception as e:
        logger.exception(f"Error saving GeoJSON to {filename}")
        raise e

def load_geojson(file_path):
    """
    Load GeoJSON data from a file
    
    Args:
        file_path: The path to the GeoJSON file
        
    Returns:
        dict: The loaded GeoJSON data
    """
    try:
        if not os.path.exists(file_path):
            logger.error(f"GeoJSON file not found: {file_path}")
            return None
            
        with open(file_path, 'r') as f:
            geojson_data = json.load(f)
        
        logger.info(f"Loaded GeoJSON from: {file_path}")
        return geojson_data
    except Exception as e:
        logger.exception(f"Error loading GeoJSON from {file_path}")
        raise e

def get_most_recent_polygon(directory):
    """
    Get the most recently modified polygon file in the directory
    
    Args:
        directory: The directory to search in
        
    Returns:
        dict: The loaded GeoJSON data or None if no polygon files found
    """
    try:
        polygon_files = sorted(list(Path(directory).glob("polygon_*.geojson")), 
                             key=os.path.getmtime, reverse=True)
        
        if not polygon_files:
            logger.warning(f"No polygon files found in {directory}")
            return None
            
        # Use the most recent polygon file
        try:
            return load_geojson(polygon_files[0])
        except Exception as e:
            logger.error(f"Error reading polygon file: {str(e)}")
            return None
    except Exception as e:
        logger.exception(f"Error getting most recent polygon from {directory}")
        return None 