"""
Async task definitions for terrain processing
"""
import logging
from celery_config import app as celery_app
from services.srtm import get_srtm_data, process_srtm_files
from services.terrain import (
    calculate_slopes, calculate_aspect, calculate_geomorphons,
    calculate_hypsometrically_tinted_hillshade, calculate_drainage_network,
    generate_contours
)
from services.database import DatabaseService
from concurrent.futures import ThreadPoolExecutor
import os
import json

logger = logging.getLogger(__name__)

# Initialize database service
db_service = DatabaseService()

@celery_app.task(bind=True, name='services.tasks.process_terrain_async')
def process_terrain_async(self, polygon_id, geojson_data, data_source='srtm'):
    """
    Async terrain processing task
    
    Args:
        polygon_id: Unique identifier for the polygon
        geojson_data: GeoJSON polygon data
        data_source: 'srtm' or 'lidar'
        
    Returns:
        dict: Processing results
    """
    try:
        # Update task status
        self.update_state(state='PROGRESS', meta={'status': 'Starting terrain processing'})
        
        # Update database status
        db_service.update_polygon_status(polygon_id, 'processing')
        
        if data_source == 'srtm':
            return process_srtm_terrain_async(self, polygon_id, geojson_data)
        elif data_source == 'lidar':
            return process_lidar_terrain_async(self, polygon_id, geojson_data)
        else:
            raise ValueError(f"Unknown data source: {data_source}")
            
    except Exception as e:
        logger.error(f"Error in async terrain processing: {str(e)}", exc_info=True)
        db_service.update_polygon_status(polygon_id, 'error')
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise

def process_srtm_terrain_async(task, polygon_id, geojson_data):
    """Process SRTM terrain data asynchronously"""
    try:
        # Step 1: Fetch SRTM data
        task.update_state(state='PROGRESS', meta={'status': 'Fetching SRTM data'})
        srtm_files = get_srtm_data(geojson_data)
        
        if not srtm_files:
            raise ValueError("No SRTM data available for the specified area")
        
        # Step 2: Process SRTM files
        task.update_state(state='PROGRESS', meta={'status': 'Processing SRTM files'})
        srtm_results = process_srtm_files(srtm_files, geojson_data)
        
        if not srtm_results:
            raise ValueError("Failed to process SRTM files")
        
        # Step 3: Parallel terrain analysis
        task.update_state(state='PROGRESS', meta={'status': 'Running terrain analysis'})
        terrain_results = process_terrain_parallel(
            srtm_results['clipped_srtm_path'], 
            polygon_id
        )
        
        # Step 4: Save analysis results to database
        task.update_state(state='PROGRESS', meta={'status': 'Saving results'})
        
        # Prepare analysis data for database
        analysis_data = {
            'srtm_path': srtm_results.get('clipped_srtm_path'),
            'visualization_path': srtm_results.get('visualization_path'),
            'slope_path': terrain_results.get('slope', {}).get('path'),
            'aspect_path': terrain_results.get('aspect', {}).get('path'),
            'contours_path': terrain_results.get('contours', {}).get('path'),
            'statistics': {
                'min_height': srtm_results.get('min_height'),
                'max_height': srtm_results.get('max_height'),
                'bounds': srtm_results.get('bounds')
            }
        }
        
        # CRITICAL FIX: Save analysis results to database
        save_result = db_service.save_analysis_results(polygon_id, analysis_data)
        
        if save_result and save_result.get('status') == 'success':
            # Set status to 'completed' only on successful save
            db_service.update_polygon_status(polygon_id, 'completed')
            logger.info(f"✅ Analysis results saved successfully for {polygon_id}. Status set to 'completed'.")
        else:
            # Log the failure and set a dedicated error status
            error_message = save_result.get('message', 'save_analysis_results returned None/False.') if save_result else 'save_analysis_results returned None/False.'
            logger.error(f"❌ FAILED to save analysis results for {polygon_id}: {error_message}. Status set to 'analysis_save_failed'.")
            db_service.update_polygon_status(polygon_id, 'analysis_save_failed')
        
        # Return results
        return {
            'status': 'completed',
            'polygon_id': polygon_id,
            'srtm_results': srtm_results,
            'terrain_results': terrain_results,
            'analysis_saved': save_result.get('status') == 'success' if save_result else False
        }
        
    except Exception as e:
        logger.error(f"Error processing SRTM terrain: {str(e)}", exc_info=True)
        db_service.update_polygon_status(polygon_id, 'error')
        raise

def process_lidar_terrain_async(task, polygon_id, geojson_data):
    """Process LiDAR terrain data asynchronously"""
    try:
        # Step 1: Detect LiDAR tiles
        task.update_state(state='PROGRESS', meta={'status': 'Detecting LiDAR tiles'})
        lidar_tiles = detect_lidar_tiles(geojson_data)
        
        if not lidar_tiles:
            raise ValueError("No LiDAR data available for the specified area")
        
        # Step 2: Create VRT if multiple tiles
        task.update_state(state='PROGRESS', meta={'status': 'Creating LiDAR mosaic'})
        vrt_path = create_lidar_vrt(lidar_tiles, polygon_id)
        
        # Step 3: Parallel LiDAR terrain analysis
        task.update_state(state='PROGRESS', meta={'status': 'Running LiDAR analysis'})
        terrain_results = process_lidar_terrain_parallel(vrt_path, geojson_data, polygon_id)
        
        # Step 4: Save analysis results to database
        task.update_state(state='PROGRESS', meta={'status': 'Saving results'})
        
        # Prepare analysis data for database
        analysis_data = {
            'srtm_path': terrain_results.get('elevation', {}).get('path'),
            'slope_path': terrain_results.get('slope', {}).get('path'),
            'aspect_path': terrain_results.get('aspect', {}).get('path'),
            'contours_path': terrain_results.get('contours', {}).get('path'),
            'statistics': {
                'data_source': 'lidar'
            }
        }
        
        # CRITICAL FIX: Save analysis results to database
        save_result = db_service.save_analysis_results(polygon_id, analysis_data)
        
        if save_result and save_result.get('status') == 'success':
            # Set status to 'completed' only on successful save
            db_service.update_polygon_status(polygon_id, 'completed')
            logger.info(f"✅ Analysis results saved successfully for {polygon_id}. Status set to 'completed'.")
        else:
            # Log the failure and set a dedicated error status
            error_message = save_result.get('message', 'save_analysis_results returned None/False.') if save_result else 'save_analysis_results returned None/False.'
            logger.error(f"❌ FAILED to save analysis results for {polygon_id}: {error_message}. Status set to 'analysis_save_failed'.")
            db_service.update_polygon_status(polygon_id, 'analysis_save_failed')
        
        return {
            'status': 'completed',
            'polygon_id': polygon_id,
            'data_source': 'lidar',
            'terrain_results': terrain_results,
            'analysis_saved': save_result.get('status') == 'success' if save_result else False
        }
        
    except Exception as e:
        logger.error(f"Error processing LiDAR terrain: {str(e)}", exc_info=True)
        db_service.update_polygon_status(polygon_id, 'error')
        raise

def process_terrain_parallel(srtm_path, polygon_id):
    """Process all terrain operations in parallel"""
    output_dir = f"/app/data/polygon_sessions/{polygon_id}"
    os.makedirs(output_dir, exist_ok=True)
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all terrain operations concurrently
        futures = {
            'slope': executor.submit(
                calculate_slopes, 
                srtm_path, 
                f"{output_dir}/slope.tif"
            ),
            'aspect': executor.submit(
                calculate_aspect, 
                srtm_path, 
                f"{output_dir}/aspect.tif"
            ),
            'geomorphons': executor.submit(
                calculate_geomorphons, 
                srtm_path, 
                f"{output_dir}/geomorphons.tif"
            ),
            'hillshade': executor.submit(
                calculate_hypsometrically_tinted_hillshade, 
                srtm_path, 
                f"{output_dir}/hillshade.tif"
            ),
            'drainage': executor.submit(
                calculate_drainage_network, 
                srtm_path, 
                f"{output_dir}/drainage.tif"
            ),
            'contours': executor.submit(
                generate_contours, 
                srtm_path, 
                f"{output_dir}/contours.geojson",
                10  # 10m contour interval
            )
        }
        
        # Wait for all operations to complete
        results = {}
        for name, future in futures.items():
            try:
                success = future.result(timeout=300)  # 5-minute timeout per operation
                results[name] = {
                    'success': success,
                    'path': f"{output_dir}/{name}.{'tif' if name != 'contours' else 'geojson'}"
                }
                logger.info(f"✅ {name} processing completed: {success}")
            except Exception as e:
                logger.error(f"❌ {name} processing failed: {str(e)}")
                results[name] = {'success': False, 'error': str(e)}
                
        return results

def process_lidar_terrain_parallel(vrt_path, geojson_data, polygon_id):
    """Process LiDAR terrain data with parallel operations"""
    output_dir = f"/app/data/polygon_sessions/{polygon_id}"
    os.makedirs(output_dir, exist_ok=True)
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        # Enhanced LiDAR processing with more operations
        futures = {
            'elevation': executor.submit(process_lidar_elevation, vrt_path, geojson_data, f"{output_dir}/elevation.tif"),
            'slope': executor.submit(process_lidar_slope, vrt_path, geojson_data, f"{output_dir}/slope.tif"),
            'aspect': executor.submit(process_lidar_aspect, vrt_path, geojson_data, f"{output_dir}/aspect.tif"),
            'hillshade': executor.submit(process_lidar_hillshade, vrt_path, geojson_data, f"{output_dir}/hillshade.tif"),
            'geomorphons': executor.submit(process_lidar_geomorphons, vrt_path, geojson_data, f"{output_dir}/geomorphons.tif"),
            'drainage': executor.submit(process_lidar_drainage, vrt_path, geojson_data, f"{output_dir}/drainage.tif")
        }
        
        results = {}
        for name, future in futures.items():
            try:
                success = future.result(timeout=600)  # 10-minute timeout for LiDAR
                results[name] = {
                    'success': success,
                    'path': f"{output_dir}/{name}.tif"
                }
                logger.info(f"✅ LiDAR {name} processing completed: {success}")
            except Exception as e:
                logger.error(f"❌ LiDAR {name} processing failed: {str(e)}")
                results[name] = {'success': False, 'error': str(e)}
                
        return results

# Placeholder functions for LiDAR processing (to be implemented)
def detect_lidar_tiles(geojson_data):
    """Detect available LiDAR tiles for the given area"""
    # TODO: Implement LiDAR tile detection
    return []

def create_lidar_vrt(lidar_tiles, polygon_id):
    """Create VRT from multiple LiDAR tiles"""
    # TODO: Implement VRT creation
    return None

def process_lidar_elevation(vrt_path, geojson_data, output_path):
    """Process LiDAR elevation data"""
    # TODO: Implement LiDAR elevation processing
    return True

def process_lidar_slope(vrt_path, geojson_data, output_path):
    """Process LiDAR slope data"""
    # TODO: Implement LiDAR slope processing
    return True

def process_lidar_aspect(vrt_path, geojson_data, output_path):
    """Process LiDAR aspect data"""
    # TODO: Implement LiDAR aspect processing
    return True

def process_lidar_hillshade(vrt_path, geojson_data, output_path):
    """Process LiDAR hillshade data"""
    # TODO: Implement LiDAR hillshade processing
    return True

def process_lidar_geomorphons(vrt_path, geojson_data, output_path):
    """Process LiDAR geomorphons data"""
    # TODO: Implement LiDAR geomorphons processing
    return True

def process_lidar_drainage(vrt_path, geojson_data, output_path):
    """Process LiDAR drainage data"""
    # TODO: Implement LiDAR drainage processing
    return True
