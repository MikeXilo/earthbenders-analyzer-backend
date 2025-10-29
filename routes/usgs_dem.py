#!/usr/bin/env python3
"""
USGS 3DEP DEM API Routes

Handles USGS 3DEP DEM processing API endpoints:
- Check if polygon is in US bounds
- Process USGS DEM for terrain analysis
- Return analysis results
"""

from flask import Blueprint, request, jsonify
from utils.cors import jsonify_with_cors
import logging
from typing import Dict, Any
import os

# Import the USGS DEM processor
from services.usgs_dem_processor import process_usgs_dem

logger = logging.getLogger(__name__)

# Create Blueprint for USGS DEM routes
usgs_dem_bp = Blueprint('usgs_dem', __name__, url_prefix='/api/usgs-dem')

@usgs_dem_bp.route('/check', methods=['POST'])
def check_usgs_dem_availability():
    """
    Check if USGS 3DEP DEM is available for the given polygon
    
    Request body:
    {
        "polygon_geometry": {
            "type": "Polygon",
            "coordinates": [[[lon1, lat1], [lon2, lat2], ...]]
        }
    }
    
    Returns:
    {
        "available": true/false,
        "message": "USGS 3DEP DEM available" or "Polygon outside US bounds"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify_with_cors({'error': 'No JSON data provided'}), 400
        
        polygon_geometry = data.get('polygon_geometry')
        if not polygon_geometry:
            return jsonify_with_cors({'error': 'polygon_geometry is required'}), 400
        
        # Import the processor to check bounds
        from services.usgs_dem_processor import usgs_dem_processor
        
        # Check if polygon is in US bounds
        is_in_us = usgs_dem_processor._is_in_us_bounds(polygon_geometry)
        
        if is_in_us:
            return jsonify_with_cors({
                'available': True,
                'message': 'USGS 3DEP DEM available for this area',
                'data_source': 'usgs-dem'
            })
        else:
            return jsonify_with_cors({
                'available': False,
                'message': 'Polygon is outside US bounds - USGS 3DEP DEM not available',
                'data_source': 'srtm'  # Fallback to SRTM
            })
            
    except Exception as e:
        logger.error(f"Error checking USGS DEM availability: {str(e)}")
        return jsonify_with_cors({'error': f'Error checking USGS DEM availability: {str(e)}'}), 500

@usgs_dem_bp.route('/process', methods=['POST'])
def process_usgs_dem_analysis():
    """
    Process USGS 3DEP DEM for terrain analysis
    
    Request body:
    {
        "polygon_geometry": {
            "type": "Polygon", 
            "coordinates": [[[lon1, lat1], [lon2, lat2], ...]]
        },
        "polygon_id": "unique_polygon_identifier",
        "user_id": "user_identifier"
    }
    
    Returns:
    {
        "success": true/false,
        "dem_path": "/app/data/polygon_sessions/polygon_id/polygon_id_srtm.tif",
        "message": "USGS DEM processing completed successfully"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify_with_cors({'error': 'No JSON data provided'}), 400
        
        polygon_geometry = data.get('polygon_geometry')
        polygon_id = data.get('polygon_id')
        user_id = data.get('user_id', None)  # Extract user_id for database saving
        
        if not polygon_geometry:
            return jsonify_with_cors({'error': 'polygon_geometry is required'}), 400
        if not polygon_id:
            return jsonify_with_cors({'error': 'polygon_id is required'}), 400
        
        logger.info(f"🚀 USGS DEM ROUTE CALLED - Processing USGS DEM for polygon {polygon_id}")
        logger.info(f"📊 USGS DEM Request data: {data}")
        
        # PHASE 1: USGS DEM-specific preparation (download, merge, reproject, clip)
        logger.info("PHASE 1: Starting USGS DEM data preparation (download, merge, reproject, clip)")
        
        # Process USGS DEM
        dem_path = process_usgs_dem(polygon_geometry, polygon_id)
        
        if not dem_path:
            return jsonify_with_cors({
                'status': 'error',
                'message': 'USGS DEM preparation failed to produce a clipped DEM file'
            }), 500
            
        logger.info(f"PHASE 1: USGS DEM ready at {dem_path}. Proceeding to unified analysis.")
        
        # PHASE 2: Unified analysis & visualization (using proven SRTM logic)
        logger.info("PHASE 2: Starting unified analysis & visualization (using SRTM logic)")
        from services.dem_processor import process_dem_files
        
        # Use unified DEM pipeline with USGS DEM file
        results = process_dem_files(
            [dem_path],  # Pass as list to match DEM function signature
            polygon_geometry,
            f"/app/data/polygon_sessions/{polygon_id}",
            'usgs-dem'  # Specify data source
        )
        
        if not results or not results.get('image'):
            return jsonify_with_cors({
                'status': 'error',
                'message': 'USGS DEM analysis failed to produce visualization'
            }), 500
        
        # PHASE 3: Calculate statistics and save to database
        logger.info("PHASE 3: Calculating statistics and saving USGS DEM analysis results to database")
        from services.database import DatabaseService
        from services.analysis_statistics import calculate_terrain_statistics
        
        db_service = DatabaseService()
        
        # Calculate statistics for USGS DEM data
        logger.info("Calculating USGS DEM terrain statistics...")
        statistics = calculate_terrain_statistics(
            dem_path=dem_path,
            slope_path=None,  # USGS DEM doesn't have slope/aspect files yet
            aspect_path=None,
            bounds=results.get('bounds', {}),
            data_source='usgs-dem'  # Pass data source for appropriate NoData handling
        )
        logger.info(f"USGS DEM statistics calculated: {statistics}")
        
        # Prepare analysis data for database (following SRTM/LiDAR pattern)
        analysis_data = {
            'dem_path': dem_path,  # Store USGS DEM in dem_path field
            'visualization_path': results.get('visualization_path'),
            'data_source': 'usgs-dem'
        }
        
        # Add statistics at root level (not nested)
        analysis_data.update(statistics)
        
        # Save analysis results to database with user_id
        save_result = db_service.save_analysis_results(polygon_id, analysis_data, user_id)
        
        if save_result and save_result.get('status') == 'success':
            logger.info(f"✅ USGS DEM analysis results saved successfully for {polygon_id}")
            return jsonify_with_cors({
                'success': True,
                'dem_path': dem_path,
                'message': 'USGS DEM processing completed successfully',
                'data_source': 'usgs-dem',
                'image': results.get('image'),
                'bounds': results.get('bounds'),
                'statistics': results.get('statistics')
            })
        else:
            error_message = save_result.get('message', 'Database save failed') if save_result else 'Database save returned None'
            logger.error(f"❌ CRITICAL: FAILED to save USGS DEM analysis results for {polygon_id}: {error_message}")
            return jsonify_with_cors({
                'success': False,
                'error': f'Database save failed: {error_message}'
            }), 500
            
    except ValueError as e:
        # Handle specific errors like "Polygon outside US bounds"
        logger.warning(f"USGS DEM processing failed: {str(e)}")
        return jsonify_with_cors({
            'success': False,
            'error': str(e),
            'fallback': 'srtm'
        }), 400
        
    except Exception as e:
        logger.error(f"Error processing USGS DEM: {str(e)}")
        return jsonify_with_cors({
            'success': False,
            'error': f'Error processing USGS DEM: {str(e)}'
        }), 500

@usgs_dem_bp.route('/status', methods=['GET'])
def get_usgs_dem_status():
    """
    Get USGS DEM processor status and configuration
    
    Returns:
    {
        "status": "operational",
        "cache_directory": "/app/data/LidarUSA",
        "supported_resolutions": ["1m", "3m", "5m"],
        "api_endpoint": "https://tnmaccess.nationalmap.gov/api/v1/products"
    }
    """
    try:
        from services.usgs_dem_processor import usgs_dem_processor
        
        # Check if cache directory exists
        cache_exists = os.path.exists(usgs_dem_processor.cache_directory)
        
        return jsonify_with_cors({
            'status': 'operational' if cache_exists else 'cache_directory_missing',
            'cache_directory': usgs_dem_processor.cache_directory,
            'cache_exists': cache_exists,
            'supported_resolutions': ['1m', '3m', '5m'],
            'api_endpoint': usgs_dem_processor.products_url,
            'wgs84_crs': str(usgs_dem_processor.wgs84_crs)
        })
        
    except Exception as e:
        logger.error(f"Error getting USGS DEM status: {str(e)}")
        return jsonify_with_cors({
            'status': 'error',
            'error': f'Error getting status: {str(e)}'
        }), 500
