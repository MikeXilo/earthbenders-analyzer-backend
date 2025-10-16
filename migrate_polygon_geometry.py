#!/usr/bin/env python3
"""
Add geometry column to polygons table to store polygon geometry directly
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def migrate_polygon_geometry():
    """Add geometry column to polygons table"""
    
    # Get database URL from environment
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not set in environment variables")
        return False
    
    try:
        # Connect to database
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        print("🔗 Connected to database successfully")
        
        # Add geometry column to polygons table
        cursor.execute("""
            ALTER TABLE polygons 
            ADD COLUMN IF NOT EXISTS geometry JSONB;
        """)
        print("✅ Added geometry column to polygons table")
        
        # Create index on geometry column for better performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_polygons_geometry 
            ON polygons USING GIN (geometry);
        """)
        print("✅ Created index on geometry column")
        
        # Commit changes
        conn.commit()
        cursor.close()
        conn.close()
        
        print("🎉 Polygon geometry migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error migrating polygon geometry: {str(e)}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    print("🚀 Migrating polygon geometry...")
    success = migrate_polygon_geometry()
    if success:
        print("✅ Polygon geometry migration complete!")
    else:
        print("❌ Polygon geometry migration failed!")
        exit(1)
