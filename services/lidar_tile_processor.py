"""
Optimized LiDAR tile processing for 90,000 small GeoTIFF files
Uses parallel processing with GDAL/Rasterio for maximum efficiency
"""
import os
import logging
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import rasterio
from rasterio.mask import mask
from shapely.geometry import shape
import numpy as np
from services.terrain import (
    calculate_slopes, calculate_aspect, calculate_geomorphons,
    calculate_hypsometrically_tinted_hillshade, calculate_drainage_network
)

logger = logging.getLogger(__name__)

def process_lidar_tiles_parallel(polygon_geometry, lidar_directory, output_dir, polygon_id):
    """
    Process LiDAR tiles in parallel for maximum efficiency
    
    Args:
        polygon_geometry: GeoJSON polygon for clipping
        lidar_directory: Path to directory containing 90,000 LiDAR tiles
        output_dir: Directory to save results
        polygon_id: Polygon identifier
        
    Returns:
        dict: Processing results
    """
    try:
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info(f"Starting parallel LiDAR processing for polygon {polygon_id}")
        logger.info(f"Scanning LiDAR directory: {lidar_directory}")
        
        # Find all GeoTIFF files in the LiDAR directory
        lidar_pattern = os.path.join(lidar_directory, "**", "*.tif")
        lidar_files = glob.glob(lidar_pattern, recursive=True)
        
        logger.info(f"Found {len(lidar_files)} LiDAR tiles")
        
        if not lidar_files:
            return {'error': 'No LiDAR tiles found in the specified directory'}
        
        # Filter tiles that intersect with the polygon
        intersecting_tiles = filter_tiles_by_polygon(lidar_files, polygon_geometry)
        
        logger.info(f"Found {len(intersecting_tiles)} tiles intersecting with polygon")
        
        if not intersecting_tiles:
            return {'error': 'No LiDAR tiles intersect with the specified polygon'}
        
        # Process tiles in parallel batches
        results = process_tile_batches_parallel(
            intersecting_tiles, 
            polygon_geometry, 
            output_dir, 
            polygon_id
        )
        
        return results
        
    except Exception as e:
        logger.error(f"Error in parallel LiDAR processing: {str(e)}", exc_info=True)
        return {'error': str(e)}

def filter_tiles_by_polygon(tile_paths, polygon_geometry):
    """
    Filter tiles that intersect with the polygon to avoid unnecessary processing
    
    Args:
        tile_paths: List of tile file paths
        polygon_geometry: GeoJSON polygon geometry
        
    Returns:
        list: Tiles that intersect with the polygon
    """
    intersecting_tiles = []
    polygon_shape = shape(polygon_geometry['geometry'])
    
    for tile_path in tile_paths:
        try:
            with rasterio.open(tile_path) as src:
                # Get tile bounds
                tile_bounds = src.bounds
                
                # Create a simple bounding box check
                from shapely.geometry import box
                tile_bbox = box(tile_bounds.left, tile_bounds.bottom, 
                              tile_bounds.right, tile_bounds.top)
                
                # Check if tile intersects with polygon
                if polygon_shape.intersects(tile_bbox):
                    intersecting_tiles.append(tile_path)
                    
        except Exception as e:
            logger.warning(f"Could not check tile {tile_path}: {str(e)}")
            continue
    
    return intersecting_tiles

def process_tile_batches_parallel(tile_paths, polygon_geometry, output_dir, polygon_id):
    """
    Process tiles in parallel batches for optimal performance
    
    Args:
        tile_paths: List of intersecting tile paths
        polygon_geometry: GeoJSON polygon for clipping
        output_dir: Output directory
        polygon_id: Polygon identifier
        
    Returns:
        dict: Processing results
    """
    try:
        # Process tiles in batches of 10 for optimal memory usage
        batch_size = 10
        batches = [tile_paths[i:i + batch_size] for i in range(0, len(tile_paths), batch_size)]
        
        logger.info(f"Processing {len(tile_paths)} tiles in {len(batches)} batches of {batch_size}")
        
        # Process batches in parallel
        with ThreadPoolExecutor(max_workers=4) as executor:
            batch_futures = []
            
            for i, batch in enumerate(batches):
                future = executor.submit(
                    process_tile_batch,
                    batch,
                    polygon_geometry,
                    output_dir,
                    f"{polygon_id}_batch_{i}"
                )
                batch_futures.append(future)
            
            # Collect results
            results = {
                'total_tiles': len(tile_paths),
                'total_batches': len(batches),
                'processed_batches': 0,
                'successful_tiles': 0,
                'failed_tiles': 0,
                'output_files': []
            }
            
            for future in as_completed(batch_futures):
                try:
                    batch_result = future.result(timeout=600)  # 10-minute timeout per batch
                    results['processed_batches'] += 1
                    results['successful_tiles'] += batch_result.get('successful_tiles', 0)
                    results['failed_tiles'] += batch_result.get('failed_tiles', 0)
                    results['output_files'].extend(batch_result.get('output_files', []))
                    
                    logger.info(f"Batch {results['processed_batches']}/{len(batches)} completed")
                    
                except Exception as e:
                    logger.error(f"Batch processing failed: {str(e)}")
                    results['failed_tiles'] += len(batch)
        
        logger.info(f"Parallel LiDAR processing completed: {results['successful_tiles']} successful, {results['failed_tiles']} failed")
        
        # Create final VRT mosaics for each terrain type
        if results['successful_tiles'] > 0:
            logger.info("Creating final VRT mosaics...")
            mosaic_results = create_final_mosaics(results['output_files'], output_dir, polygon_id)
            results['mosaics'] = mosaic_results
        
        return results
        
    except Exception as e:
        logger.error(f"Error in batch processing: {str(e)}", exc_info=True)
        return {'error': str(e)}

def process_tile_batch(tile_paths, polygon_geometry, output_dir, batch_id):
    """
    Process a batch of tiles sequentially (within the batch)
    
    Args:
        tile_paths: List of tile paths in this batch
        polygon_geometry: GeoJSON polygon for clipping
        output_dir: Output directory
        batch_id: Batch identifier
        
    Returns:
        dict: Batch processing results
    """
    try:
        results = {
            'batch_id': batch_id,
            'successful_tiles': 0,
            'failed_tiles': 0,
            'output_files': []
        }
        
        polygon_shape = shape(polygon_geometry['geometry'])
        
        for tile_path in tile_paths:
            try:
                # Process individual tile
                output_files = process_single_tile(
                    tile_path, 
                    polygon_shape, 
                    output_dir, 
                    batch_id
                )
                
                if output_files:
                    results['successful_tiles'] += 1
                    results['output_files'].extend(output_files)
                else:
                    results['failed_tiles'] += 1
                    
            except Exception as e:
                logger.error(f"Failed to process tile {tile_path}: {str(e)}")
                results['failed_tiles'] += 1
        
        return results
        
    except Exception as e:
        logger.error(f"Error processing batch {batch_id}: {str(e)}", exc_info=True)
        return {
            'batch_id': batch_id,
            'successful_tiles': 0,
            'failed_tiles': len(tile_paths),
            'output_files': [],
            'error': str(e)
        }

def process_single_tile(tile_path, polygon_shape, output_dir, batch_id):
    """
    Process a single LiDAR tile with all terrain operations
    
    Args:
        tile_path: Path to the LiDAR tile
        polygon_shape: Shapely polygon for clipping
        output_dir: Output directory
        batch_id: Batch identifier
        
    Returns:
        list: Output file paths
    """
    try:
        # Get tile filename for output naming
        tile_name = Path(tile_path).stem
        output_files = []
        
        # Create output paths
        base_output_path = os.path.join(output_dir, f"{batch_id}_{tile_name}")
        
        # Process each terrain operation
        terrain_operations = {
            'slope': (calculate_slopes, f"{base_output_path}_slope.tif"),
            'aspect': (calculate_aspect, f"{base_output_path}_aspect.tif"),
            'geomorphons': (calculate_geomorphons, f"{base_output_path}_geomorphons.tif"),
            'hillshade': (calculate_hypsometrically_tinted_hillshade, f"{base_output_path}_hillshade.tif"),
            'drainage': (calculate_drainage_network, f"{base_output_path}_drainage.tif")
        }
        
        for operation_name, (operation_func, output_path) in terrain_operations.items():
            try:
                # Run terrain operation
                success = operation_func(tile_path, output_path)
                
                if success and os.path.exists(output_path):
                    output_files.append(output_path)
                    logger.debug(f"✅ {operation_name} completed for {tile_name}")
                else:
                    logger.warning(f"❌ {operation_name} failed for {tile_name}")
                    
            except Exception as e:
                logger.error(f"Error in {operation_name} for {tile_name}: {str(e)}")
        
        return output_files
        
    except Exception as e:
        logger.error(f"Error processing single tile {tile_path}: {str(e)}", exc_info=True)
        return []

def create_final_mosaics(output_files, output_dir, polygon_id):
    """
    Create final VRT mosaics for each terrain type
    
    Args:
        output_files: List of all output file paths
        output_dir: Output directory
        polygon_id: Polygon identifier
        
    Returns:
        dict: Mosaic results
    """
    try:
        import subprocess
        from pathlib import Path
        
        # Group files by terrain type
        terrain_files = {
            'slope': [],
            'aspect': [],
            'geomorphons': [],
            'hillshade': [],
            'drainage': []
        }
        
        for file_path in output_files:
            filename = Path(file_path).name
            for terrain_type in terrain_files.keys():
                if f"_{terrain_type}.tif" in filename:
                    terrain_files[terrain_type].append(file_path)
                    break
        
        mosaic_results = {}
        
        # Create VRT mosaic for each terrain type
        for terrain_type, files in terrain_files.items():
            if not files:
                continue
                
            logger.info(f"Creating {terrain_type} mosaic from {len(files)} tiles")
            
            # Create VRT file
            vrt_path = os.path.join(output_dir, f"{polygon_id}_{terrain_type}.vrt")
            final_tif_path = os.path.join(output_dir, f"{polygon_id}_{terrain_type}_final.tif")
            
            try:
                # Build VRT using GDAL
                vrt_cmd = [
                    'gdalbuildvrt',
                    '-resolution', 'highest',
                    '-overwrite',
                    vrt_path
                ] + files
                
                result = subprocess.run(vrt_cmd, capture_output=True, text=True, timeout=300)
                
                if result.returncode == 0:
                    # Convert VRT to final GeoTIFF
                    tif_cmd = [
                        'gdal_translate',
                        '-of', 'GTiff',
                        '-co', 'COMPRESS=LZW',
                        '-co', 'TILED=YES',
                        vrt_path,
                        final_tif_path
                    ]
                    
                    tif_result = subprocess.run(tif_cmd, capture_output=True, text=True, timeout=300)
                    
                    if tif_result.returncode == 0:
                        mosaic_results[terrain_type] = {
                            'vrt_path': vrt_path,
                            'final_tif_path': final_tif_path,
                            'tile_count': len(files),
                            'status': 'success'
                        }
                        logger.info(f"✅ {terrain_type} mosaic created successfully")
                    else:
                        logger.error(f"❌ Failed to create final TIF for {terrain_type}: {tif_result.stderr}")
                        mosaic_results[terrain_type] = {
                            'status': 'failed',
                            'error': tif_result.stderr
                        }
                else:
                    logger.error(f"❌ Failed to create VRT for {terrain_type}: {result.stderr}")
                    mosaic_results[terrain_type] = {
                        'status': 'failed',
                        'error': result.stderr
                    }
                    
            except subprocess.TimeoutExpired:
                logger.error(f"❌ Timeout creating {terrain_type} mosaic")
                mosaic_results[terrain_type] = {
                    'status': 'failed',
                    'error': 'Timeout during VRT creation'
                }
            except Exception as e:
                logger.error(f"❌ Error creating {terrain_type} mosaic: {str(e)}")
                mosaic_results[terrain_type] = {
                    'status': 'failed',
                    'error': str(e)
                }
        
        return mosaic_results
        
    except Exception as e:
        logger.error(f"Error creating final mosaics: {str(e)}", exc_info=True)
        return {'error': str(e)}
