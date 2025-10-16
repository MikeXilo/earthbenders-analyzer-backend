"""
Database service for polygon and analysis management
"""
import os
import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

class DatabaseService:
    """Database service for polygon and analysis management"""
    
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        if not self.db_url:
            logger.warning("DATABASE_URL not set, database operations will be disabled")
            self.enabled = False
        else:
            self.enabled = True
            logger.info("Database service initialized with DATABASE_URL")
            # Test database connection
            self._test_connection()
    
    def _test_connection(self):
        """Test database connection"""
        try:
            conn = psycopg2.connect(self.db_url)
            conn.close()
            logger.info("Database connection successful")
        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")
            self.enabled = False
    
    def _get_connection(self):
        """Get database connection"""
        if not self.enabled:
            return None
        try:
            return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)
        except Exception as e:
            logger.error(f"Failed to connect to database: {str(e)}")
            return None
    
    def save_polygon_metadata(self, polygon_id: str, filename: str, 
                            geojson_path: str, bounds: Dict[str, float],
                            user_id: Optional[str] = None) -> Dict[str, Any]:
        """Save polygon metadata to database"""
        if not self.enabled:
            return {'status': 'disabled', 'message': 'Database not configured'}
        
        conn = self._get_connection()
        if not conn:
            return {'status': 'error', 'message': 'Database connection failed'}
        
        try:
            cursor = conn.cursor()
            
            # Insert polygon metadata
            cursor.execute("""
                INSERT INTO polygons (id, name, filename, geojson_path, bounds, status, user_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    filename = EXCLUDED.filename,
                    geojson_path = EXCLUDED.geojson_path,
                    bounds = EXCLUDED.bounds,
                    updated_at = NOW()
            """, (
                polygon_id,
                filename.replace('.geojson', ''),  # name without extension
                filename,
                geojson_path,
                json.dumps(bounds) if bounds else None,
                'pending',
                user_id
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"Saved polygon metadata: {polygon_id}")
            return {
                'status': 'success',
                'polygon_id': polygon_id,
                'message': 'Polygon metadata saved to database'
            }
        except Exception as e:
            logger.error(f"Error saving polygon metadata: {str(e)}")
            if conn:
                conn.rollback()
                conn.close()
            return {'status': 'error', 'message': str(e)}
    
    def update_polygon_status(self, polygon_id: str, status: str) -> Dict[str, Any]:
        """Update polygon processing status"""
        if not self.enabled:
            return {'status': 'disabled'}
        
        conn = self._get_connection()
        if not conn:
            return {'status': 'error', 'message': 'Database connection failed'}
        
        try:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE polygons 
                SET status = %s, updated_at = NOW()
                WHERE id = %s
            """, (status, polygon_id))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"Updated polygon {polygon_id} status to: {status}")
            return {'status': 'success', 'message': f'Status updated to {status}'}
        except Exception as e:
            logger.error(f"Error updating polygon status: {str(e)}")
            if conn:
                conn.rollback()
                conn.close()
            return {'status': 'error', 'message': str(e)}
    
    def save_analysis_results(self, polygon_id: str, analysis_data: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
        """Save analysis results to database"""
        if not self.enabled:
            return {'status': 'disabled'}
        
        conn = self._get_connection()
        if not conn:
            return {'status': 'error', 'message': 'Database connection failed'}
        
        try:
            cursor = conn.cursor()
            
            # Insert or update analysis results
            cursor.execute("""
                INSERT INTO analyses (id, polygon_id, user_id, srtm_path, slope_path, aspect_path, contours_path, statistics, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (polygon_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    srtm_path = EXCLUDED.srtm_path,
                    slope_path = EXCLUDED.slope_path,
                    aspect_path = EXCLUDED.aspect_path,
                    contours_path = EXCLUDED.contours_path,
                    statistics = EXCLUDED.statistics,
                    updated_at = NOW()
            """, (
                f"analysis_{polygon_id}",
                polygon_id,
                user_id,
                analysis_data.get('srtm_path'),
                analysis_data.get('slope_path'),
                analysis_data.get('aspect_path'),
                analysis_data.get('contours_path'),
                json.dumps(analysis_data)
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"Saved analysis results for polygon: {polygon_id}")
            return {'status': 'success', 'message': 'Analysis results saved'}
        except Exception as e:
            logger.error(f"Error saving analysis results: {str(e)}")
            if conn:
                conn.rollback()
                conn.close()
            return {'status': 'error', 'message': str(e)}
    
    def get_analysis_record(self, polygon_id: str) -> Optional[Dict[str, Any]]:
        """Get analysis record by polygon ID"""
        if not self.enabled:
            return None
        
        conn = self._get_connection()
        if not conn:
            return None
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT a.*, p.status as polygon_status, p.bounds, p.user_id
                FROM analyses a
                JOIN polygons p ON a.polygon_id = p.id
                WHERE a.polygon_id = %s
            """, (polygon_id,))
            
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return dict(result)
            return None
            
        except Exception as e:
            logger.error(f"Error getting analysis record: {str(e)}")
            if conn:
                conn.close()
            return None
    
    def get_polygon_metadata(self, polygon_id: str) -> Optional[Dict[str, Any]]:
        """Get polygon metadata by ID"""
        if not self.enabled:
            return None
        
        conn = self._get_connection()
        if not conn:
            return None
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, filename, status, bounds, user_id, created_at
                FROM polygons
                WHERE id = %s
            """, (polygon_id,))
            
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return dict(result)
            return None
            
        except Exception as e:
            logger.error(f"Error getting polygon metadata: {str(e)}")
            if conn:
                conn.close()
            return None
    
    def update_analysis_paths(self, polygon_id: str, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update analysis record with new analysis paths"""
        if not self.enabled:
            return {'status': 'disabled'}
        
        conn = self._get_connection()
        if not conn:
            return {'status': 'error', 'message': 'Database connection failed'}
        
        try:
            cursor = conn.cursor()
            
            # Update analysis record with new paths
            cursor.execute("""
                UPDATE analyses SET
                    srtm_path = COALESCE(%s, srtm_path),
                    slope_path = COALESCE(%s, slope_path),
                    aspect_path = COALESCE(%s, aspect_path),
                    hillshade_path = COALESCE(%s, hillshade_path),
                    geomorphons_path = COALESCE(%s, geomorphons_path),
                    drainage_path = COALESCE(%s, drainage_path),
                    contours_path = COALESCE(%s, contours_path),
                    statistics = COALESCE(%s, statistics),
                    updated_at = NOW()
                WHERE polygon_id = %s
            """, (
                analysis_data.get('srtm_path'),
                analysis_data.get('slope_path'),
                analysis_data.get('aspect_path'),
                analysis_data.get('hillshade_path'),
                analysis_data.get('geomorphons_path'),
                analysis_data.get('drainage_path'),
                analysis_data.get('contours_path'),
                json.dumps(analysis_data) if analysis_data else None,
                polygon_id
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"Updated analysis paths for polygon: {polygon_id}")
            return {'status': 'success', 'message': 'Analysis paths updated'}
        except Exception as e:
            logger.error(f"Error updating analysis paths: {str(e)}")
            if conn:
                conn.rollback()
                conn.close()
            return {'status': 'error', 'message': str(e)}
    
    def save_file_metadata(self, polygon_id: str, file_name: str, file_path: str, 
                          file_type: str, file_size: Optional[int] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Save file metadata to database"""
        if not self.enabled:
            return {'status': 'disabled'}
        
        conn = self._get_connection()
        if not conn:
            return {'status': 'error', 'message': 'Database connection failed'}
        
        try:
            cursor = conn.cursor()
            
            # Insert file metadata
            cursor.execute("""
                INSERT INTO file_storage (id, polygon_id, user_id, file_name, file_path, file_type, file_size, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    file_path = EXCLUDED.file_path,
                    file_size = EXCLUDED.file_size,
                    updated_at = NOW()
            """, (
                f"file_{polygon_id}_{file_type}",
                polygon_id,
                user_id,
                file_name,
                file_path,
                file_type,
                file_size
            ))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"Saved file metadata: {file_name} for polygon {polygon_id}")
            return {'status': 'success', 'message': 'File metadata saved'}
        except Exception as e:
            logger.error(f"Error saving file metadata: {str(e)}")
            if conn:
                conn.rollback()
                conn.close()
            return {'status': 'error', 'message': str(e)}
    
    def recalculate_statistics(self, polygon_id: str) -> Dict[str, Any]:
        """Recalculate terrain statistics for a polygon"""
        if not self.enabled:
            return {'status': 'disabled'}
        
        conn = self._get_connection()
        if not conn:
            return {'status': 'error', 'message': 'Database connection failed'}
        
        try:
            cursor = conn.cursor()
            
            # Get current analysis data
            cursor.execute("""
                SELECT srtm_path, slope_path, aspect_path, statistics
                FROM analyses 
                WHERE polygon_id = %s
            """, (polygon_id,))
            
            row = cursor.fetchone()
            if not row:
                cursor.close()
                conn.close()
                return {'status': 'error', 'message': 'Analysis not found'}
            
            srtm_path = row['srtm_path']
            slope_path = row['slope_path']
            aspect_path = row['aspect_path']
            current_stats = row['statistics'] or {}
            
            # Check if we have the required files
            if not srtm_path:
                cursor.close()
                conn.close()
                return {'status': 'error', 'message': 'SRTM file not found'}
            
            # Calculate statistics if we have SRTM data
            if srtm_path:
                try:
                    # Import statistics calculation
                    from services.statistics import calculate_terrain_statistics
                    
                    # Calculate new statistics (will handle missing slope/aspect gracefully)
                    new_stats = calculate_terrain_statistics(
                        srtm_path=srtm_path,
                        slope_path=slope_path,
                        aspect_path=aspect_path,
                        bounds=current_stats.get('bounds', {})
                    )
                    
                    # Merge with existing statistics
                    updated_stats = {**current_stats, **new_stats}
                    
                    # Update database
                    cursor.execute("""
                        UPDATE analyses 
                        SET statistics = %s, updated_at = NOW()
                        WHERE polygon_id = %s
                    """, (json.dumps(updated_stats), polygon_id))
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    logger.info(f"Recalculated statistics for polygon: {polygon_id}")
                    return {'status': 'success', 'message': 'Statistics recalculated', 'statistics': updated_stats}
                    
                except Exception as e:
                    logger.error(f"Error calculating statistics: {str(e)}")
                    cursor.close()
                    conn.close()
                    return {'status': 'error', 'message': f'Statistics calculation failed: {str(e)}'}
            else:
                cursor.close()
                conn.close()
                return {'status': 'warning', 'message': 'Slope and aspect files required for statistics calculation'}
                
        except Exception as e:
            logger.error(f"Error in recalculate_statistics: {str(e)}")
            if conn:
                conn.rollback()
                conn.close()
            return {'status': 'error', 'message': str(e)}
