"""
Routes for project management and user projects
"""
import logging
import json
import os
from flask import request, jsonify
from services.database import DatabaseService

logger = logging.getLogger(__name__)

# Initialize database service
db_service = DatabaseService()

def register_routes(app):
    """
    Register all project-related routes
    
    Args:
        app: Flask application instance
    """
    
    @app.route('/api/projects', methods=['GET'])
    def get_user_projects():
        """Get projects for a specific user"""
        try:
            user_id = request.args.get('user_id')
            
            if not user_id:
                return jsonify({
                    'status': 'error',
                    'message': 'user_id parameter is required'
                }), 400
            
            logger.info(f"Fetching projects for user: {user_id}")
            
            # Query analyses table for user's projects
            conn = db_service._get_connection()
            if not conn:
                return jsonify({
                    'status': 'error',
                    'message': 'Database connection failed'
                }), 500
            
            try:
                cursor = conn.cursor()
                
                # Get all analyses for the user
                cursor.execute("""
                    SELECT 
                        a.id,
                        a.polygon_id,
                        a.user_id,
                        a.statistics,
                        a.srtm_path,
                        a.slope_path,
                        a.aspect_path,
                        a.contours_path,
                        a.hillshade_path,
                        a.geomorphons_path,
                        a.drainage_path,
                        a.created_at,
                        a.updated_at,
                        p.name as polygon_name,
                        p.status as polygon_status,
                        p.bounds as polygon_bounds,
                        p.geojson_path
                    FROM analyses a
                    LEFT JOIN polygons p ON a.polygon_id = p.id
                    WHERE a.user_id = %s
                    ORDER BY a.created_at DESC
                """, (user_id,))
                
                results = cursor.fetchall()
                logger.info(f"Found {len(results)} projects for user {user_id}")
                
                projects = []
                for row in results:
                    # Parse statistics JSON
                    statistics = {}
                    if row['statistics']:
                        try:
                            if isinstance(row['statistics'], str):
                                statistics = json.loads(row['statistics'])
                            else:
                                statistics = row['statistics']
                            logger.info(f"Parsed statistics for project {row['polygon_id']}: {statistics}")
                        except (json.JSONDecodeError, TypeError):
                            logger.warning(f"Could not parse statistics for project {row['polygon_id']}")
                            statistics = {}
                    else:
                        logger.warning(f"No statistics found for project {row['polygon_id']}")
                    
                    # Load polygon geometry from GeoJSON file
                    polygon_geometry = None
                    if row['geojson_path']:
                        try:
                            geojson_file_path = os.path.join('/app/data', row['geojson_path'])
                            if os.path.exists(geojson_file_path):
                                with open(geojson_file_path, 'r') as f:
                                    geojson_data = json.load(f)
                                    # Extract geometry from GeoJSON
                                    if geojson_data.get('type') == 'Feature':
                                        polygon_geometry = geojson_data.get('geometry')
                                    else:
                                        polygon_geometry = geojson_data
                            else:
                                logger.warning(f"GeoJSON file not found: {geojson_file_path}")
                        except Exception as e:
                            logger.warning(f"Could not load polygon geometry for project {row['polygon_id']}: {str(e)}")
                            polygon_geometry = None
                    
                    # Create analysis files object
                    analysis_files = {
                        'srtm': row['srtm_path'],
                        'slope': row['slope_path'],
                        'aspect': row['aspect_path'],
                        'contours': row['contours_path'],
                        'hillshade': row['hillshade_path'],
                        'geomorphons': row['geomorphons_path'],
                        'drainage': row['drainage_path']
                    }
                    
                    # Parse polygon bounds if available
                    bounds = None
                    if row['polygon_bounds']:
                        try:
                            if isinstance(row['polygon_bounds'], str):
                                bounds = json.loads(row['polygon_bounds'])
                            else:
                                bounds = row['polygon_bounds']
                        except (json.JSONDecodeError, TypeError):
                            logger.warning(f"Could not parse bounds for project {row['polygon_id']}")
                    
                    project = {
                        'polygon_id': row['polygon_id'],
                        'polygon_name': row['polygon_name'] or f"Analysis {row['polygon_id'][-8:]}",
                        'status': row['polygon_status'] or 'completed',
                        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                        'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
                        'statistics': statistics,
                        'analysis_files': analysis_files,
                        'bounds': bounds,
                        'geometry': polygon_geometry
                    }
                    
                    projects.append(project)
                
                cursor.close()
                conn.close()
                
                return jsonify({
                    'status': 'success',
                    'projects': projects,
                    'count': len(projects)
                })
                
            except Exception as e:
                logger.error(f"Error querying projects: {str(e)}")
                if conn:
                    conn.rollback()
                    conn.close()
                return jsonify({
                    'status': 'error',
                    'message': f'Database query failed: {str(e)}'
                }), 500
                
        except Exception as e:
            logger.error(f"Error in get_user_projects: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @app.route('/api/projects/<polygon_id>/statistics', methods=['POST'])
    def calculate_project_statistics(polygon_id):
        """Calculate statistics for a specific project"""
        try:
            logger.info(f"Calculating statistics for project: {polygon_id}")
            
            # Get the recalculate_statistics result
            result = db_service.recalculate_statistics(polygon_id)
            
            if result.get('status') == 'success':
                return jsonify({
                    'status': 'success',
                    'statistics': result.get('statistics', {}),
                    'message': 'Statistics calculated successfully'
                })
            else:
                return jsonify({
                    'status': 'error',
                    'message': result.get('message', 'Statistics calculation failed')
                }), 400
                
        except Exception as e:
            logger.error(f"Error calculating statistics for project {polygon_id}: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    
    @app.route('/api/projects/<project_id>', methods=['GET'])
    def get_project_details(project_id):
        """Get detailed information for a specific project"""
        try:
            logger.info(f"Fetching project details for: {project_id}")
            
            conn = db_service._get_connection()
            if not conn:
                return jsonify({
                    'status': 'error',
                    'message': 'Database connection failed'
                }), 500
            
            try:
                cursor = conn.cursor()
                
                # Get project details with all analysis files
                cursor.execute("""
                    SELECT 
                        a.id,
                        a.polygon_id,
                        a.user_id,
                        a.statistics,
                        a.srtm_path,
                        a.slope_path,
                        a.aspect_path,
                        a.contours_path,
                        a.hillshade_path,
                        a.geomorphons_path,
                        a.drainage_path,
                        a.created_at,
                        a.updated_at,
                        p.name as polygon_name,
                        p.status as polygon_status,
                        p.bounds as polygon_bounds,
                        p.geometry as polygon_geometry,
                        p.geojson_path
                    FROM analyses a
                    LEFT JOIN polygons p ON a.polygon_id = p.id
                    WHERE a.polygon_id = %s
                """, (project_id,))
                
                row = cursor.fetchone()
                if not row:
                    cursor.close()
                    conn.close()
                    return jsonify({
                        'status': 'error',
                        'message': 'Project not found'
                    }), 404
                
                # Parse statistics
                statistics = {}
                if row['statistics']:
                    try:
                        statistics = json.loads(row['statistics']) if isinstance(row['statistics'], str) else row['statistics']
                    except:
                        statistics = {}
                
                # Parse bounds
                bounds = {}
                if row['polygon_bounds']:
                    try:
                        bounds = json.loads(row['polygon_bounds']) if isinstance(row['polygon_bounds'], str) else row['polygon_bounds']
                    except:
                        bounds = {}
                
                # Build analysis files object
                analysis_files = {
                    'srtm': row['srtm_path'],
                    'slope': row['slope_path'],
                    'aspect': row['aspect_path'],
                    'contours': row['contours_path'],
                    'hillshade': row['hillshade_path'],
                    'geomorphons': row['geomorphons_path'],
                    'drainage': row['drainage_path']
                }
                
                # Load polygon geometry from database first, then fallback to file
                polygon_geometry = None
                
                # Try to get geometry from database first
                if row['polygon_geometry']:
                    try:
                        polygon_geometry = json.loads(row['polygon_geometry']) if isinstance(row['polygon_geometry'], str) else row['polygon_geometry']
                        logger.info(f"Loaded polygon geometry from database for project {project_id}")
                    except Exception as e:
                        logger.warning(f"Could not parse polygon geometry from database: {str(e)}")
                        polygon_geometry = None
                
                # Fallback to loading from GeoJSON file if not in database
                if not polygon_geometry and row['geojson_path']:
                    try:
                        geojson_file_path = os.path.join('/app/data', row['geojson_path'])
                        if os.path.exists(geojson_file_path):
                            with open(geojson_file_path, 'r') as f:
                                geojson_data = json.load(f)
                                # Extract geometry from GeoJSON
                                if geojson_data.get('type') == 'Feature':
                                    polygon_geometry = geojson_data.get('geometry')
                                else:
                                    polygon_geometry = geojson_data
                            logger.info(f"Loaded polygon geometry from file for project {project_id}")
                        else:
                            logger.warning(f"GeoJSON file not found: {geojson_file_path}")
                    except Exception as e:
                        logger.warning(f"Could not load polygon geometry from file for project {project_id}: {str(e)}")
                        polygon_geometry = None
                
                project = {
                    'polygon_id': row['polygon_id'],
                    'polygon_name': row['polygon_name'] or f"Analysis {row['polygon_id'][-8:]}",
                    'status': row['polygon_status'] or 'completed',
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                    'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
                    'statistics': statistics,
                    'analysis_files': analysis_files,
                    'bounds': bounds,
                    'geometry': polygon_geometry
                }
                
                cursor.close()
                conn.close()
                
                return jsonify({
                    'status': 'success',
                    'project': project
                })
                
            except Exception as e:
                logger.error(f"Error fetching project details: {str(e)}")
                if conn:
                    conn.rollback()
                    cursor.close()
                    conn.close()
                return jsonify({
                    'status': 'error',
                    'message': f'Database query failed: {str(e)}'
                }), 500
                
        except Exception as e:
            logger.error(f"Error in get_project_details: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @app.route('/api/projects/<project_id>/name', methods=['PUT'])
    def update_project_name(project_id):
        """Update the name of a project"""
        try:
            data = request.json
            new_name = data.get('name')
            
            if not new_name:
                return jsonify({
                    'status': 'error',
                    'message': 'name is required'
                }), 400
            
            logger.info(f"Updating project name: {project_id} -> {new_name}")
            
            conn = db_service._get_connection()
            if not conn:
                return jsonify({
                    'status': 'error',
                    'message': 'Database connection failed'
                }), 500
            
            try:
                cursor = conn.cursor()
                
                # First, get the user_id for this project to check for duplicates
                cursor.execute("""
                    SELECT a.user_id 
                    FROM analyses a 
                    WHERE a.polygon_id = %s
                """, (project_id,))
                
                user_result = cursor.fetchone()
                if not user_result:
                    cursor.close()
                    conn.close()
                    return jsonify({
                        'status': 'error',
                        'message': 'Project not found'
                    }), 404
                
                user_id = user_result[0]
                
                # Check for duplicate names within the same user's projects
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM polygons p
                    JOIN analyses a ON p.id = a.polygon_id
                    WHERE a.user_id = %s 
                    AND p.name = %s 
                    AND p.id != %s
                """, (user_id, new_name.strip(), project_id))
                
                duplicate_count = cursor.fetchone()[0]
                if duplicate_count > 0:
                    cursor.close()
                    conn.close()
                    return jsonify({
                        'status': 'error',
                        'message': 'A project with this name already exists for this user'
                    }), 409
                
                # Update the polygon name
                cursor.execute("""
                    UPDATE polygons 
                    SET name = %s, updated_at = NOW()
                    WHERE id = %s
                """, (new_name.strip(), project_id))
                
                if cursor.rowcount == 0:
                    cursor.close()
                    conn.close()
                    return jsonify({
                        'status': 'error',
                        'message': 'Project not found'
                    }), 404
                
                conn.commit()
                cursor.close()
                conn.close()
                
                return jsonify({
                    'status': 'success',
                    'message': 'Project name updated successfully'
                })
                
            except Exception as e:
                logger.error(f"Error updating project name: {str(e)}")
                if conn:
                    conn.rollback()
                    conn.close()
                return jsonify({
                    'status': 'error',
                    'message': f'Database update failed: {str(e)}'
                }), 500
                
        except Exception as e:
            logger.error(f"Error in update_project_name: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
