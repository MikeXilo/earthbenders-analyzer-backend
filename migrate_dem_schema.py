#!/usr/bin/env python3
"""
Database Migration: Rename srtm_path to dem_path

This script migrates the database schema to rename the misleading srtm_path field
to the more accurate dem_path field.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

def migrate_dem_schema():
    """Migrate database schema from srtm_path to dem_path"""
    try:
        # Get database URL from environment
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            logger.error("DATABASE_URL environment variable not set")
            return False
        
        # Connect to database
        conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        cursor = conn.cursor()
        
        logger.info("Starting database migration: srtm_path → dem_path")
        
        # Check if srtm_path column exists
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_name = 'analyses' AND column_name = 'srtm_path'
        """)
        srtm_path_exists = cursor.fetchone()[0] > 0
        
        # Check if dem_path column exists
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_name = 'analyses' AND column_name = 'dem_path'
        """)
        dem_path_exists = cursor.fetchone()[0] > 0
        
        # Case 1: dem_path exists, srtm_path doesn't - already migrated
        if dem_path_exists and not srtm_path_exists:
            logger.info("✅ Migration already complete (dem_path exists, srtm_path removed)")
            cursor.close()
            conn.close()
            return True
        
        # Case 2: Both exist - migration interrupted, clean up
        if dem_path_exists and srtm_path_exists:
            logger.info("⚠️  Both columns exist - completing interrupted migration")
            cursor.execute("ALTER TABLE analyses DROP COLUMN srtm_path")
            conn.commit()
            logger.info("✅ Removed old srtm_path column")
            cursor.close()
            conn.close()
            return True
        
        # Case 3: srtm_path exists, dem_path doesn't - do migration
        if srtm_path_exists and not dem_path_exists:
            logger.info("Starting migration: srtm_path → dem_path")
            
            # Add dem_path column
            cursor.execute("ALTER TABLE analyses ADD COLUMN dem_path TEXT")
            logger.info("Added dem_path column")
            
            # Copy data
            cursor.execute("UPDATE analyses SET dem_path = srtm_path WHERE srtm_path IS NOT NULL")
            logger.info("Copied data from srtm_path to dem_path")
            
            # Drop old column
            cursor.execute("ALTER TABLE analyses DROP COLUMN srtm_path")
            logger.info("Dropped srtm_path column")
            
            conn.commit()
            logger.info("✅ Migration completed successfully")
            cursor.close()
            conn.close()
            return True
        
        # Case 4: Neither exists - create dem_path
        if not dem_path_exists and not srtm_path_exists:
            logger.info("Neither column exists - adding dem_path")
            cursor.execute("ALTER TABLE analyses ADD COLUMN dem_path TEXT")
            conn.commit()
            logger.info("✅ Added dem_path column")
            cursor.close()
            conn.close()
            return True
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Database migration failed: {str(e)}")
        return False

if __name__ == "__main__":
    success = migrate_dem_schema()
    if success:
        print("🎉 Database migration completed successfully!")
    else:
        print("❌ Database migration failed!")
        exit(1)
