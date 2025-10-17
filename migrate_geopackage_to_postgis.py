#!/usr/bin/env python3
"""
Migrate GeoPackage spatial index to PostGIS table
"""
import os
import geopandas as gpd
from sqlalchemy import create_engine, text
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_geopackage_to_postgis():
    """Migrate GeoPackage to PostGIS table"""
    try:
        # Get database URL
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            logger.error("❌ DATABASE_URL not found in environment variables")
            return False
        
        # Create database engine
        engine = create_engine(database_url)
        
        # Step 1: Enable PostGIS extension
        logger.info("🔧 Enabling PostGIS extension...")
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            conn.commit()
        logger.info("✅ PostGIS extension enabled")
        
        # Step 2: Read GeoPackage
        geopackage_path = "data/lidarpt2m2025tiles.gpkg"
        if not os.path.exists(geopackage_path):
            logger.error(f"❌ GeoPackage not found: {geopackage_path}")
            return False
        
        logger.info(f"📖 Reading GeoPackage: {geopackage_path}")
        gdf = gpd.read_file(geopackage_path)
        logger.info(f"📊 Loaded {len(gdf)} tiles from GeoPackage")
        
        # Step 3: Prepare data for PostGIS
        # Rename columns to match our schema
        if 'NAME' in gdf.columns:
            gdf = gdf.rename(columns={'NAME': 'name'})
        
        # Add s3_path column (we'll construct this from the name)
        gdf['s3_path'] = gdf['name'].apply(lambda x: f"MDT-2m/MDT-2m-{x}-" if x else None)
        
        # Ensure geometry column is named 'geometry'
        if 'geometry' not in gdf.columns:
            gdf = gdf.rename(columns={gdf.geometry.name: 'geometry'})
        
        # Select only the columns we need
        columns_to_keep = ['name', 's3_path', 'geometry']
        gdf = gdf[columns_to_keep]
        
        logger.info("📤 Inserting data into PostGIS table...")
        
        # Step 4: Insert into PostGIS table
        gdf.to_postgis(
            "lidarpt2m2025tiles", 
            engine, 
            if_exists="replace",
            index=True
        )
        
        logger.info("✅ Data inserted successfully")
        
        # Step 5: Create spatial index
        logger.info("🔧 Creating spatial index...")
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_lidarpt2m2025tiles_geometry 
                ON lidarpt2m2025tiles USING GIST (geometry);
            """))
            conn.commit()
        
        logger.info("✅ Spatial index created")
        
        # Step 6: Verify the data
        logger.info("🔍 Verifying data...")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM lidarpt2m2025tiles;"))
            count = result.scalar()
            logger.info(f"✅ Table contains {count} tiles")
        
        logger.info("🎉 Migration completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error during migration: {str(e)}")
        return False

if __name__ == "__main__":
    migrate_geopackage_to_postgis()
