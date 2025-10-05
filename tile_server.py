import os
import logging
from flask import Flask, send_file, jsonify
import sqlite3
import io

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tile_server")

class TileServer:
    def __init__(self, app, base_path=None):
        """
        Initialize the tile server with a Flask app and base path for MBTiles files
        
        Args:
            app: Flask application instance
            base_path: Base directory where MBTiles files are stored
        """
        self.app = app
        
        # Default base path if none provided
        if base_path is None:
            self.base_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 
                'data', 'basemaps', 'portugal', 'REN2023'
            )
        else:
            self.base_path = base_path
            
        logger.info(f"Tile server initialized with base path: {self.base_path}")
        
        # Register routes
        self.register_routes()
    
    def register_routes(self):
        """Register all tile-related routes with the Flask app"""
        
        @self.app.route('/api/tiles/<layer_name>/<int:z>/<int:x>/<int:y>.pbf')
        def get_tile(layer_name, z, x, y):
            return self.serve_tile(layer_name, z, x, y)
        
        @self.app.route('/api/tiles/<layer_name>/metadata')
        def get_metadata(layer_name):
            return self.serve_metadata(layer_name)
    
    def serve_tile(self, layer_name, z, x, y):
        """
        Serve a vector tile for the specified layer and coordinates
        
        Args:
            layer_name: Name of the layer (MBTiles file without extension)
            z: Zoom level
            x: Tile column
            y: Tile row
            
        Returns:
            Tile data as binary response
        """
        try:
            # Construct the path to the MBTiles file
            mbtiles_path = os.path.join(self.base_path, f"{layer_name}.mbtiles")
            
            if not os.path.exists(mbtiles_path):
                logger.error(f"MBTiles file not found: {mbtiles_path}")
                return jsonify({'error': 'Tile source not found'}), 404
            
            # Connect to the SQLite database (MBTiles is a SQLite database)
            conn = sqlite3.connect(mbtiles_path)
            
            # MBTiles uses TMS coordinates, but web maps use XYZ coordinates
            # Convert y coordinate from XYZ to TMS
            flipped_y = (1 << z) - 1 - y
            
            # Get the tile data
            logger.info(f"Fetching tile {z}/{x}/{flipped_y} from {layer_name}")
            tile_data = conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                (z, x, flipped_y)
            ).fetchone()
            
            conn.close()
            
            if tile_data:
                # Return the tile as a binary response with appropriate headers
                response = send_file(
                    io.BytesIO(tile_data[0]),
                    mimetype="application/x-protobuf",
                    as_attachment=False
                )
                
                # Add cache headers (1 day cache)
                response.headers.add('Cache-Control', 'public, max-age=86400')
                return response
            else:
                # Return empty response for missing tiles
                logger.info(f"Tile {z}/{x}/{y} not found in {layer_name}")
                return "", 204
                
        except Exception as e:
            logger.error(f"Error serving tile {z}/{x}/{y} from {layer_name}: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    def serve_metadata(self, layer_name):
        """
        Serve metadata for the specified layer
        
        Args:
            layer_name: Name of the layer (MBTiles file without extension)
            
        Returns:
            JSON metadata for the layer
        """
        try:
            # Construct the path to the MBTiles file
            mbtiles_path = os.path.join(self.base_path, f"{layer_name}.mbtiles")
            
            if not os.path.exists(mbtiles_path):
                logger.error(f"MBTiles file not found: {mbtiles_path}")
                return jsonify({'error': 'Tile source not found'}), 404
            
            # Connect to the SQLite database (MBTiles is a SQLite database)
            conn = sqlite3.connect(mbtiles_path)
            
            # Get metadata from the metadata table
            metadata = {}
            for name, value in conn.execute("SELECT name, value FROM metadata"):
                metadata[name] = value
            
            conn.close()
            
            # Add some default styling parameters if not present
            if 'style' not in metadata:
                metadata['style'] = {
                    'color': '#ff0000',
                    'weight': 1,
                    'opacity': 0.5,
                    'fillColor': '#ff0000',
                    'fillOpacity': 0.2
                }
            
            # Convert JSON string to object if it exists
            if 'json' in metadata and isinstance(metadata['json'], str):
                import json
                try:
                    metadata['json'] = json.loads(metadata['json'])
                except:
                    pass
            
            return jsonify(metadata)
            
        except Exception as e:
            logger.error(f"Error serving metadata for {layer_name}: {str(e)}")
            return jsonify({'error': str(e)}), 500 