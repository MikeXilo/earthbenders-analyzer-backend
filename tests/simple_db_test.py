#!/usr/bin/env python3
"""
Simple database connection test
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def test_db_connection():
    """Test basic database connection and queries"""
    try:
        # Set DATABASE_URL
        database_url = "postgresql://neondb_owner:npg_hbUvX2K5BczS@ep-cool-lake-a9k6x6wf-pooler.gwc.azure.neon.tech/earthbenders-analyzer?sslmode=require&channel_binding=require"
        
        # Connect directly
        conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        cursor = conn.cursor()
        
        # Test basic query
        cursor.execute("SELECT 1 as test")
        result = cursor.fetchone()
        print(f"✅ Basic query works: {result}")
        
        # Check if PostGIS is enabled
        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'postgis')")
        postgis_enabled = cursor.fetchone()
        print(f"✅ PostGIS enabled: {postgis_enabled['exists']}")
        
        # Check if our table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'lidarpt2m2025tiles'
            )
        """)
        table_exists = cursor.fetchone()
        print(f"✅ Table exists: {table_exists['exists']}")
        
        if table_exists['exists']:
            # Get count
            cursor.execute("SELECT COUNT(*) FROM lidarpt2m2025tiles")
            count = cursor.fetchone()
            print(f"✅ Table has {count['count']} rows")
            
            # Get sample data
            cursor.execute("SELECT name, s3_path FROM lidarpt2m2025tiles LIMIT 3")
            samples = cursor.fetchall()
            print(f"✅ Sample data: {samples}")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Database error: {str(e)}")
        return False

if __name__ == "__main__":
    test_db_connection()
