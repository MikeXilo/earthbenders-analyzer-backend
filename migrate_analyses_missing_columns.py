#!/usr/bin/env python3
"""
Migration script to add missing columns to analyses table
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def migrate_analyses_missing_columns():
    """Add missing columns to analyses table"""
    
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not set in environment variables")
        return False
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        print("🔗 Connected to database successfully")
        
        # Add missing columns to analyses table
        print("🔄 Adding missing columns to analyses table...")
        
        cursor.execute("""
            ALTER TABLE analyses 
            ADD COLUMN IF NOT EXISTS user_id VARCHAR(255),
            ADD COLUMN IF NOT EXISTS final_dem_path TEXT,
            ADD COLUMN IF NOT EXISTS data_source VARCHAR(50),
            ADD COLUMN IF NOT EXISTS hillshade_path TEXT,
            ADD COLUMN IF NOT EXISTS geomorphons_path TEXT,
            ADD COLUMN IF NOT EXISTS drainage_path TEXT
        """)
        
        print("✅ Added missing columns to analyses table")
        
        # Create index on user_id for better performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_analyses_user_id ON analyses(user_id)
        """)
        print("✅ Created index on user_id")
        
        # Create index on data_source for filtering
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_analyses_data_source ON analyses(data_source)
        """)
        print("✅ Created index on data_source")
        
        conn.commit()
        print("🎉 Migration completed successfully!")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error during migration: {str(e)}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    print("🚀 Adding missing columns to analyses table...")
    success = migrate_analyses_missing_columns()
    if success:
        print("✅ Migration complete!")
    else:
        print("❌ Migration failed!")
        exit(1)
