#!/usr/bin/env python3
"""
Create database tables for the basemap application
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def create_tables():
    """Create all required database tables"""
    
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
        
        # Create polygons table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS polygons (
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255),
                filename VARCHAR(255) NOT NULL,
                geojson_path TEXT NOT NULL,
                srtm_path TEXT,
                slope_path TEXT,
                bounds JSONB,
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                user_id VARCHAR(255)
            );
        """)
        print("✅ Created polygons table")
        
        # Create analyses table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id VARCHAR(255) PRIMARY KEY,
                polygon_id VARCHAR(255) UNIQUE NOT NULL,
                elevation JSONB,
                slope JSONB,
                aspect JSONB,
                contours JSONB,
                statistics JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (polygon_id) REFERENCES polygons(id) ON DELETE CASCADE
            );
        """)
        print("✅ Created analyses table")
        
        # Create file_storage table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_storage (
                id VARCHAR(255) PRIMARY KEY,
                polygon_id VARCHAR(255) NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                file_path TEXT NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                file_size INTEGER,
                mime_type VARCHAR(100),
                azure_url TEXT,
                is_in_azure BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (polygon_id) REFERENCES polygons(id) ON DELETE CASCADE
            );
        """)
        print("✅ Created file_storage table")
        
        # Create users table (for future use)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(255) PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                name VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        print("✅ Created users table")
        
        # Create indexes for better performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_polygons_status ON polygons(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_polygons_user_id ON polygons(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_storage_polygon_id ON file_storage(polygon_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_storage_file_type ON file_storage(file_type);")
        print("✅ Created database indexes")
        
        # Commit changes
        conn.commit()
        cursor.close()
        conn.close()
        
        print("🎉 Database tables created successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error creating tables: {str(e)}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    print("🚀 Creating database tables...")
    success = create_tables()
    if success:
        print("✅ Database setup complete!")
    else:
        print("❌ Database setup failed!")
        exit(1)
