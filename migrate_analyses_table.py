#!/usr/bin/env python3
"""
Migration script to update analyses table schema
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def migrate_analyses_table():
    """Migrate analyses table from old schema to new schema"""
    
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not set in environment variables")
        return False
    
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        print("🔗 Connected to database successfully")
        
        # Check if old columns exist
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'analyses' 
            AND table_schema = 'public'
            AND column_name IN ('elevation', 'slope', 'aspect', 'contours')
        """)
        old_columns = [row[0] for row in cursor.fetchall()]
        
        if old_columns:
            print(f"🔄 Found old columns: {old_columns}")
            print("🔄 Migrating analyses table...")
            
            # Add new columns
            cursor.execute("""
                ALTER TABLE analyses 
                ADD COLUMN IF NOT EXISTS srtm_path TEXT,
                ADD COLUMN IF NOT EXISTS slope_path TEXT,
                ADD COLUMN IF NOT EXISTS aspect_path TEXT,
                ADD COLUMN IF NOT EXISTS contours_path TEXT
            """)
            print("✅ Added new columns")
            
            # Drop old columns
            for column in old_columns:
                cursor.execute(f"ALTER TABLE analyses DROP COLUMN IF EXISTS {column}")
                print(f"✅ Dropped old column: {column}")
            
            conn.commit()
            print("🎉 Migration completed successfully!")
            
        else:
            print("✅ Table already has correct schema")
            
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
    print("🚀 Migrating analyses table schema...")
    success = migrate_analyses_table()
    if success:
        print("✅ Migration complete!")
    else:
        print("❌ Migration failed!")
        exit(1)
