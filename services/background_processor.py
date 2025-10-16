"""
Simple background processing without Celery
Uses Python threading for immediate background processing
"""
import threading
import logging
import time
from typing import Dict, Any, Optional
from services.srtm import get_srtm_data, process_srtm_files
from services.terrain import (
    calculate_slopes, calculate_aspect, calculate_geomorphons,
    calculate_hypsometrically_tinted_hillshade, calculate_drainage_network,
    generate_contours
)
from services.database import DatabaseService
from services.statistics import calculate_terrain_statistics
from concurrent.futures import ThreadPoolExecutor
import os
import json

logger = logging.getLogger(__name__)

# Initialize database service
db_service = DatabaseService()

# Global task status tracking
task_status = {}

def run_terrain_analysis(polygon_id: str, geojson_data: Dict[str, Any], data_source: str = 'srtm') -> str:
    """
    Start background terrain processing
    
    Args:
        polygon_id: Unique identifier for the polygon
        geojson_data: GeoJSON polygon data
        data_source: 'srtm' or 'lidar'
        
    Returns:
        str: Task ID for status tracking
    """
    task_id = f"task_{polygon_id}_{int(time.time())}"
    
    # Initialize task status
    task_status[task_id] = {
        'status': 'PROGRESS',
        'message': 'Starting terrain processing',
        'polygon_id': polygon_id,
        'data_source': data_source,
        'progress': 0
    }
    
    # Start background thread
    thread = threading.Thread(
        target=_process_terrain_worker,
        args=(task_id, polygon_id, geojson_data, data_source),
        daemon=True
    )
    thread.start()
    
    logger.info(f"🚀 Started background processing for {polygon_id} (task: {task_id})")
    return task_id

def _process_terrain_worker(task_id: str, polygon_id: str, geojson_data: Dict[str, Any], data_source: str):
    """
    Background worker function for terrain processing
    """
    try:
        # Update task status
        task_status[task_id]['status'] = 'PROGRESS'
        task_status[task_id]['message'] = 'Updating database status'
        task_status[task_id]['progress'] = 10
        
        # Update database status
        db_service.update_polygon_status(polygon_id, 'processing')
        
        if data_source == 'srtm':
            _process_srtm_terrain(task_id, polygon_id, geojson_data)
        elif data_source == 'lidar':
            _process_lidar_terrain(task_id, polygon_id, geojson_data)
        else:
            raise ValueError(f"Unknown data source: {data_source}")
            
    except Exception as e:
        logger.error(f"❌ Background processing failed for {polygon_id}: {str(e)}", exc_info=True)
        task_status[task_id]['status'] = 'FAILURE'
        task_status[task_id]['message'] = f'Processing failed: {str(e)}'
        task_status[task_id]['progress'] = 0
        db_service.update_polygon_status(polygon_id, 'error')
        raise

def _process_srtm_terrain(task_id: str, polygon_id: str, geojson_data: Dict[str, Any]):
    """Process SRTM terrain data - CRITICAL: Always updates database status"""
    try:
        # Step 1: Fetch SRTM data
        task_status[task_id]['message'] = 'Fetching SRTM data'
        task_status[task_id]['progress'] = 20
        
        srtm_files = get_srtm_data(geojson_data)
        if not srtm_files:
            raise ValueError("No SRTM data available for the specified area")
        
        # Step 2: Process SRTM files (now returns partial data on visualization failure)
        task_status[task_id]['message'] = 'Processing SRTM files'
        task_status[task_id]['progress'] = 40
        
        srtm_results = process_srtm_files(srtm_files, geojson_data)
        if not srtm_results:
            raise ValueError("Failed to process SRTM files")
        
        # Step 3: Parallel terrain analysis
        task_status[task_id]['message'] = 'Running terrain analysis'
        task_status[task_id]['progress'] = 60
        
        terrain_results = _process_terrain_parallel(
            srtm_results['clipped_srtm_path'], 
            polygon_id
        )
        
        # Step 4: Calculate comprehensive statistics
        task_status[task_id]['message'] = 'Calculating statistics'
        task_status[task_id]['progress'] = 75
        
        # Calculate terrain statistics using the statistics service
        statistics = calculate_terrain_statistics(
            srtm_path=srtm_results.get('clipped_srtm_path'),
            slope_path=terrain_results.get('slope', {}).get('path'),
            aspect_path=terrain_results.get('aspect', {}).get('path'),
            bounds=srtm_results.get('bounds', {})
        )
        
        # Prepare analysis data for database
        analysis_data = {
            'srtm_path': srtm_results.get('clipped_srtm_path'),
            'visualization_path': srtm_results.get('visualization_path'),
            'slope_path': terrain_results.get('slope', {}).get('path'),
            'aspect_path': terrain_results.get('aspect', {}).get('path'),
            'contours_path': terrain_results.get('contours', {}).get('path'),
            'statistics': statistics
        }
        
        # Step 5: Save analysis results to database
        task_status[task_id]['message'] = 'Saving results'
        task_status[task_id]['progress'] = 80
        
        # Save analysis results to database
        save_result = db_service.save_analysis_results(polygon_id, analysis_data)
        
        if save_result and save_result.get('status') == 'success':
            # Set status to 'completed' only on successful save
            db_service.update_polygon_status(polygon_id, 'completed')
            logger.info(f"✅ Analysis results saved successfully for {polygon_id}")
            
            # Update task status to success
            task_status[task_id]['status'] = 'SUCCESS'
            task_status[task_id]['message'] = 'Terrain analysis completed successfully'
            task_status[task_id]['progress'] = 100
            task_status[task_id]['results'] = {
                'srtm_results': srtm_results,
                'terrain_results': terrain_results,
                'analysis_saved': True
            }
        else:
            # CRITICAL: Log the failure and set a dedicated error status
            error_message = save_result.get('message', 'save_analysis_results failed') if save_result else 'save_analysis_results returned None'
            logger.error(f"❌ CRITICAL: FAILED to save analysis results for {polygon_id}: {error_message}")
            db_service.update_polygon_status(polygon_id, 'failed')  # Use 'failed' instead of 'analysis_save_failed'
            
            task_status[task_id]['status'] = 'FAILURE'
            task_status[task_id]['message'] = f'Database save failed: {error_message}'
            task_status[task_id]['progress'] = 80
        
    except Exception as e:
        logger.error(f"❌ SRTM processing failed for {polygon_id}: {str(e)}", exc_info=True)
        db_service.update_polygon_status(polygon_id, 'error')
        task_status[task_id]['status'] = 'FAILURE'
        task_status[task_id]['message'] = f'SRTM processing failed: {str(e)}'
        task_status[task_id]['progress'] = 0
        raise

def _process_lidar_terrain(task_id: str, polygon_id: str, geojson_data: Dict[str, Any]):
    """Process LiDAR terrain data"""
    # TODO: Implement LiDAR processing
    logger.warning("LiDAR processing not yet implemented")
    task_status[task_id]['status'] = 'FAILURE'
    task_status[task_id]['message'] = 'LiDAR processing not yet implemented'
    task_status[task_id]['progress'] = 0

def _process_terrain_parallel(srtm_path: str, polygon_id: str) -> Dict[str, Any]:
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

def get_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the status of a background task
    
    Args:
        task_id: Task identifier
        
    Returns:
        dict: Task status information or None if not found
    """
    return task_status.get(task_id)

def cleanup_completed_tasks():
    """Clean up completed tasks older than 1 hour"""
    current_time = time.time()
    tasks_to_remove = []
    
    for task_id, status in task_status.items():
        if status.get('status') in ['SUCCESS', 'FAILURE']:
            # Check if task is older than 1 hour
            if current_time - int(task_id.split('_')[-1]) > 3600:
                tasks_to_remove.append(task_id)
    
    for task_id in tasks_to_remove:
        del task_status[task_id]
        logger.info(f"🧹 Cleaned up completed task: {task_id}")
