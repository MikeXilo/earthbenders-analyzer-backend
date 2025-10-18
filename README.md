# Earthbenders Analyzer Backend

....

A Flask-based geospatial analysis backend that processes polygon data, generates terrain analysis, and manages file storage with database integration.

## 🏗️ Architecture

### **Database Layer (Neon PostgreSQL)**
- **Polygon metadata** - Bounds, status, user associations
- **Analysis results** - SRTM processing, slope analysis, contours
- **File tracking** - Metadata for all generated files
- **User management** - Ready for future authentication

### **File Storage (Railway Volumes)**
- **SRTM Cache** - Reusable raw SRTM tiles in `/app/data/srtms/`
- **Session Folders** - User-specific processed data in `/app/data/polygon_sessions/{id}/`
- **GeoJSON files** - User-drawn polygons
- **Processed outputs** - Clipped SRTM, slope, contours, analysis results
- **Future Azure migration** - Easy transition path

## 🚀 Deployment

### **Railway Configuration**
- **Builder:** Dockerfile
- **Start Command:** `gunicorn --bind 0.0.0.0:${PORT:-8000} server:app`
- **Environment Variables:**
  - `DATABASE_URL` - Neon PostgreSQL connection string
  - `PORT` - Server port (auto-set by Railway)
  - `SAVE_DIRECTORY` - File storage path (`/app/data`)

### **Database Setup**
Tables are created automatically on startup via `create_tables.py`:
- `polygons` - Polygon metadata and status
- `analyses` - Analysis results and statistics
- `file_storage` - File metadata and paths
- `users` - User management (future)

### **Current Status: Production Ready ✅**
- **Database Integration:** Neon PostgreSQL fully operational with geometry storage
- **File Storage:** Railway volumes with optimized SRTM cache structure
- **SRTM Processing:** ✅ **WORKING PERFECTLY** - Optimized workflow with cached tiles
- **LIDAR Processing:** ✅ **WORKING PERFECTLY** - High-resolution DEM with unified pipeline
- **API Endpoints:** All core operations tested and working
- **Error Handling:** Robust error management implemented
- **Performance:** SRTM tiles cached for reuse across sessions
- **Background Processing:** Simple threading-based async processing (Celery-free, in-memory task tracking)
- **Polygon Geometry:** Database-first storage with file fallback for project viewing
- **Unified Architecture:** ✅ **LIDAR + SRTM** both working with same visualization pipeline

## 📊 API Endpoints

### **Core Polygon Operations**

#### `POST /save_polygon`
Save a polygon to database and file system.

**Request:**
```json
{
  "data": {
    "type": "Feature",
    "geometry": {
      "type": "Polygon",
      "coordinates": [[[lon, lat], ...]]
    }
  },
  "filename": "polygon.geojson",
  "id": "polygon-id-123"
}
```

**Response:**
```json
{
  "message": "Polygon saved successfully",
  "file_path": "/app/data/polygon_sessions/polygon-id-123/polygon.geojson",
  "database_status": {
    "status": "success",
    "polygon_id": "polygon-id-123"
  },
  "file_metadata_status": {
    "status": "success",
    "message": "File metadata saved"
  }
}
```

#### `POST /process_polygon`
Process SRTM data for a polygon and generate terrain analysis.

**Request:**
```json
{
  "data": {
    "type": "Feature",
    "geometry": {
      "type": "Polygon",
      "coordinates": [[[lon, lat], ...]]
    }
  },
  "id": "polygon-id-123",
  "filename": "polygon.geojson"
}
```

**Response:**
```json
{
  "message": "Polygon processed successfully. SRTM data clipped and saved.",
  "polygon_id": "polygon-id-123",
  "srtm_file_path": "/app/data/polygon_sessions/polygon-id-123/polygon-id-123_srtm.tif",
  "bounds": [minLon, minLat, maxLon, maxLat],
  "database_status": "saved",
  "file_metadata_status": {
    "status": "success",
    "message": "File metadata saved"
  },
  "srtm_cache_status": "tiles_reused_from_cache"
}
```

### **Analysis Operations**

#### `POST /centroid`
Calculate the centroid of a polygon.

**Request:**
```json
{
  "points": [[lon, lat], [lon, lat], ...]
}
```

**Response:**
```json
{
  "centroid": [lon, lat]
}
```

#### `PATCH /update_analysis_paths/<analysisId>`
Update analysis record with raster file paths.

**Request:**
```json
{
  "paths": {
    "srtm_path": "/path/to/srtm.tif",
    "slope_path": "/path/to/slope.tif"
  }
}
```

### **Health & Monitoring**

#### `GET /`
Root endpoint with service status.

**Response:**
```json
{
  "status": "Flask service running",
  "message": "API is active and serving routes.",
  "version": "6.1",
  "routes_loaded": true
}
```

#### `GET /db-health`
Database connection and table status check.

**Response:**
```json
{
  "status": "connected",
  "message": "Database connection successful",
  "tables_exist": ["polygons", "analyses", "file_storage", "users"],
  "tables_expected": ["polygons", "analyses", "file_storage", "users"],
  "all_tables_present": true
}
```

## 🗄️ Database Schema

### **Polygons Table**
```sql
CREATE TABLE polygons (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255),
    filename VARCHAR(255) NOT NULL,
    geojson_path TEXT NOT NULL,
    dem_path TEXT,                    -- ✅ UPDATED: Unified DEM path (was srtm_path)
    slope_path TEXT,
    bounds JSONB,
    geometry JSONB,                   -- Stores polygon geometry directly in database
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    user_id VARCHAR(255)
);
```

### **Analyses Table**
```sql
CREATE TABLE analyses (
    id VARCHAR(255) PRIMARY KEY,
    polygon_id VARCHAR(255) UNIQUE NOT NULL,
    dem_path TEXT,                    -- ✅ Unified DEM path (was srtm_path)
    slope_path TEXT,
    aspect_path TEXT,
    hillshade_path TEXT,              -- ✅ Hillshade analysis
    geomorphons_path TEXT,            -- ✅ Geomorphons analysis
    drainage_path TEXT,               -- ✅ Drainage network
    contours_path TEXT,
    final_dem_path TEXT,              -- ✅ Final processed DEM
    data_source VARCHAR(50),          -- ✅ SRTM, LIDAR, USGS-DEM
    statistics JSONB,                 -- ✅ Terrain statistics
    bounds JSONB,                     -- ✅ Geographic bounds
    image TEXT,                       -- ✅ Base64 visualization
    status VARCHAR(50) DEFAULT 'pending', -- ✅ Processing status
    error_message TEXT,               -- ✅ Error tracking
    analysis_files JSONB,            -- ✅ Structured file paths
    processing_steps JSONB,           -- ✅ Processing progress
    user_id VARCHAR(255),             -- ✅ User tracking
    user_email VARCHAR(255),          -- ✅ User email
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (polygon_id) REFERENCES polygons(id) ON DELETE CASCADE
);
```

### **File Storage Table**
```sql
CREATE TABLE file_storage (
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
```

## 🔧 Development

### **Local Setup**
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://user:pass@host:port/db"
export SAVE_DIRECTORY="./data"

# Run the application
python server.py
```

### **Database Migration**
```bash
# Create tables manually
python create_tables.py
```

### **Testing**
```bash
# Test database health
curl https://earthbenders-analyzer-backend-production.up.railway.app/db-health

# Test polygon save
curl -X POST https://earthbenders-analyzer-backend-production.up.railway.app/save_polygon \
  -H "Content-Type: application/json" \
  -d '{"data": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}, "filename": "test.geojson", "id": "test-001"}'

# Test polygon processing (use real-world coordinates for SRTM data)
curl -X POST https://earthbenders-analyzer-backend-production.up.railway.app/process_polygon \
  -H "Content-Type: application/json" \
  -d '{"data": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[-118.25, 34.05], [-118.2, 34.05], [-118.2, 34.1], [-118.25, 34.1], [-118.25, 34.05]]]}}, "filename": "ca-test.geojson", "id": "test-002"}'
```

### **Integration Test Script**
Run the comprehensive test suite:
```bash
python test_database_integration.py
```
This tests all endpoints and validates the complete data flow.

## 📁 File Structure

```
Backend/
├── server.py                           # Main Flask application entry point
├── create_tables.py                    # Database table creation and migration scripts
├── requirements.txt                    # Python dependencies
├── Dockerfile                         # Container configuration for Railway deployment
├── railway.json                       # Railway deployment configuration
├── Procfile                           # Alternative start command for Railway
├── migrate_analyses_table.py          # Database migration: adds dem_path column
├── services/                          # Core business logic services
│   ├── database.py                    # Database service layer (CRUD operations)
│   ├── dem_processor.py              # Unified DEM processing (SRTM, LIDAR, USGS)
│   ├── srtm.py                       # SRTM-specific data processing and caching
│   ├── lidar_processor.py            # LIDAR PT data processing (ETRS89 → WGS84)
│   ├── usgs_dem_processor.py         # USGS 3DEP DEM processing for USA
│   ├── terrain.py                    # Terrain analysis (slope, aspect, geomorphons, drainage)
│   ├── terrain_parallel.py           # Parallel terrain processing for performance
│   ├── analysis_statistics.py        # Statistics calculation for all data sources
│   ├── raster_visualization.py       # Visualization generation for all terrain layers
│   ├── background_processor.py       # Background processing without Celery
│   └── lidar_tile_processor.py       # LIDAR tile processing utilities
├── routes/                           # API endpoint definitions
│   ├── polygon.py                    # Core polygon operations (save, process, centroid)
│   ├── terrain.py                    # Terrain analysis endpoints (slope, aspect, etc.)
│   ├── projects.py                   # Project management and user projects
│   ├── lidar.py                      # LIDAR-specific processing endpoints
│   └── usgs_dem.py                   # USGS DEM processing endpoints
├── scripts/                          # Utility scripts and helpers
│   └── helpers/
│       └── dem_file_finder.py        # Unified DEM file discovery (SRTM, LIDAR, USGS)
├── tests/                            # Test files and validation
│   ├── test_srtm.py                  # SRTM processing tests
│   ├── test_lidar.py                 # LIDAR processing tests
│   └── test_usgs_dem.py              # USGS DEM processing tests
└── data/                            # File storage directory (Railway volumes)
    ├── srtms/                       # SRTM cache (reusable raw tiles)
    ├── polygon_sessions/            # User-specific processed data
    │   └── {polygon_id}/            # Session folders
    │       ├── polygon.geojson       # User-drawn polygon
    │       ├── clipped_dem.tif      # Clipped elevation data
    │       ├── {id}_srtm.tif        # Legacy SRTM naming
    │       ├── {id}_slope.tif       # Slope analysis
    │       ├── {id}_aspect.tif      # Aspect analysis
    │       ├── {id}_geomorphons.tif # Geomorphons analysis
    │       ├── {id}_hillshade.tif   # Hillshade visualization
    │       └── {id}_drainage.tif    # Drainage network
    └── basemaps/                    # Base map data (future)
```

## 🔧 **File Descriptions**

### **Core Application Files**
- **`server.py`** - Main Flask application with route registration and error handling
- **`create_tables.py`** - Database schema creation and migration management
- **`requirements.txt`** - Python dependencies with geospatial libraries
- **`Dockerfile`** - Container configuration for Railway deployment

### **Services Layer (Business Logic)**
- **`database.py`** - Database CRUD operations, connection management, and query execution
- **`dem_processor.py`** - **UNIFIED DEM PROCESSING** - Handles SRTM, LIDAR PT, LIDAR US, USGS DEM with consistent visualization
- **`srtm.py`** - SRTM-specific processing with intelligent caching and tile management
- **`lidar_processor.py`** - LIDAR PT processing with ETRS89→WGS84 transformation
- **`usgs_dem_processor.py`** - USGS 3DEP DEM processing for USA territories
- **`terrain.py`** - Terrain analysis functions (slope, aspect, geomorphons, drainage, hillshade)
- **`terrain_parallel.py`** - Parallel processing for multiple terrain operations
- **`analysis_statistics.py`** - Statistics calculation with NoData handling for all sources
- **`raster_visualization.py`** - Visualization generation with transparency and color ramps
- **`background_processor.py`** - Simple threading-based async processing (Celery-free, in-memory task tracking)
- **`lidar_tile_processor.py`** - LIDAR tile processing utilities and S3 integration

### **Routes Layer (API Endpoints)**
- **`polygon.py`** - Core polygon operations (save, process, centroid calculation)
- **`terrain.py`** - Terrain analysis endpoints (slope, aspect, geomorphons, drainage, hillshade)
- **`projects.py`** - Project management and user project retrieval
- **`lidar.py`** - LIDAR-specific processing endpoints
- **`usgs_dem.py`** - USGS DEM processing endpoints

### **Utility Scripts**
- **`dem_file_finder.py`** - Unified DEM file discovery supporting multiple naming conventions
- **`migrate_analyses_table.py`** - Database migration for dem_path column

### **Test Files**
- **`test_srtm.py`** - SRTM processing validation tests
- **`test_lidar.py`** - LIDAR processing validation tests  
- **`test_usgs_dem.py`** - USGS DEM processing validation tests

### **Data Storage Structure**
- **`/data/srtms/`** - SRTM tile cache for performance optimization
- **`/data/polygon_sessions/{id}/`** - User-specific processed data with consistent naming

## 🔄 Data Flow

1. **User draws polygon** → Frontend sends GeoJSON to `/save_polygon`
2. **Backend saves metadata** → Stores in Neon database
3. **Backend saves file** → Stores GeoJSON in session folder
4. **User requests processing** → Calls `/process_polygon`
5. **Backend checks SRTM cache** → Looks in `/app/data/srtms/` for existing tiles
6. **Backend downloads if needed** → Only downloads missing SRTM tiles
7. **Backend processes data** → Clips SRTM to polygon and analyzes terrain
8. **Backend saves results** → Stores processed files in session folder
9. **Database tracks status** → Updates polygon status and results

### **Recent Fixes & Improvements**
- **Optimized SRTM Workflow:** Check cache → download if needed → clip to polygon
- **File Structure Optimization:** SRTM cache in `/app/data/srtms/`, processed data in session folders
- **Performance Enhancement:** SRTM tiles cached for reuse across sessions
- **GeoJSON Parsing:** Fixed Feature object handling in `shapely.geometry.shape()`
- **SRTM Function Calls:** Corrected parameter passing to `get_srtm_data()`
- **Database Health Check:** Improved error handling and connection management
- **Real-World Testing:** Validated with California coordinates for SRTM data
- **Error Handling:** Enhanced logging and graceful failure management
- **User Authentication Integration:** Complete user tracking across polygons, analyses, and file_storage tables
- **Real Statistics Calculation:** Automatic terrain statistics calculation (elevation, slope, aspect, area) with database integration
- **Celery Removal:** Replaced complex Celery async processing with simple Python threading
- **LIDAR WGS84-First:** Refactored LIDAR processing to transform to WGS84 before clipping for consistency
- **Polygon Geometry Storage:** Added database storage for polygon geometry with file fallback
- **API Endpoint Fixes:** Added missing `/api/analyses` endpoint for frontend communication
- **WhiteboxTools Optimization:** Implemented lazy initialization to prevent worker conflicts
- **Deployment Simplification:** Single-service Railway deployment without Celery complexity
- **🎉 MAJOR BREAKTHROUGH:** ✅ **SRTM + LIDAR BOTH WORKING** - Unified pipeline architecture
- **PostGIS Integration:** 91,196 LIDAR tiles with spatial indexing for lightning-fast queries
- **S3 Integration:** Intelligent caching with 7-day performance optimization
- **Function Signature Fix:** Corrected `process_srtm_files()` call for LIDAR pipeline
- **Statistics Format Fix:** Unified statistics format across all analysis types
- **Area Calculation Fix:** Dynamic resolution-based area calculation for accurate statistics
- **LIDAR Elevation Fix:** Proper NoData handling for complete elevation statistics
- **Transparency Fix:** Eliminated white buffer pixels in LIDAR elevation visualizations

## 🚀 Future Enhancements

### **Azure Migration (2 months)**
- Move file storage from Railway volumes to Azure Blob Storage
- Update `file_storage` table with Azure URLs
- Implement file migration scripts

### **User Authentication**
- Add user management endpoints
- Implement JWT authentication
- User-specific polygon access

### **Advanced Analysis**
- Slope analysis with Whitebox tools
- Contour generation
- Water accumulation modeling
- 3D visualization data

## 🛠️ Dependencies

### **Core Dependencies**
- `flask==2.3.3` - Web framework
- `gunicorn==21.2.0` - WSGI server
- `psycopg2-binary==2.9.7` - PostgreSQL adapter
- `sqlalchemy==2.0.23` - Database ORM

### **Geospatial Dependencies**
- `rasterio==1.3.9` - Raster data processing
- `fiona==1.9.4` - Vector data processing
- `shapely>=1.8.0` - Geometric operations
- `geopandas==0.14.3` - Geospatial data analysis
- `pyproj==3.6.1` - Coordinate transformations

### **System Dependencies (Dockerfile)**
- `libgdal-dev` - GDAL development libraries
- `libgeos-dev` - GEOS geometry library
- `libproj-dev` - PROJ coordinate transformation
- `gdal-bin` - GDAL command-line tools

## 📞 Support

For issues or questions:
- **Repository:** https://github.com/MikeXilo/earthbenders-analyzer-backend
- **Railway URL:** https://earthbenders-analyzer-backend-production.up.railway.app/
- **Database:** Neon PostgreSQL (earthbenders-analyzer)

## 🔧 Railway CLI Commands

### **SSH Access**
```bash
# Connect to Railway backend container
railway ssh --project=4befc57d-874b-4b08-94f4-0dbe29106141 --environment=33d43056-76dd-45c7-95e9-2c37c4641157 --service=b96de10d-ddea-44db-ba1f-31e253ae1f79

# Alternative using npx
npx @railway/cli ssh --project=4befc57d-874b-4b08-94f4-0dbe29106141 --environment=33d43056-76dd-45c7-95e9-2c37c4641157 --service=b96de10d-ddea-44db-ba1f-31e253ae1f79
```

### **Volume Inspection**
```bash
# List all files in the data directory
ls -la /app/data

# Check SRTM cache directory
ls -la /app/data/srtms/

# Check polygon sessions
ls -la /app/data/polygon_sessions/

# Check specific session folder
ls -la /app/data/polygon_sessions/{polygon_id}/
```

## 🧪 Test Results

### **Latest Integration Test Results**
```
🧪 Testing Database Integration
==================================================

1️⃣ Testing Service Health...
   Status: 200 ✅ Service running: API Running

2️⃣ Testing Database Health...
   Status: 200 ✅ Database status: connected

3️⃣ Testing Polygon Save...
   Status: 200 ✅ Polygon saved successfully!

4️⃣ Testing Polygon Processing...
   Status: 200 ✅ Polygon processed successfully!

5️⃣ Testing Centroid Calculation...
   Status: 200 ✅ Centroid calculated: [0.5, 0.5]

🎉 Database Integration Test Complete!
==================================================
```

---

**Version:** 6.5  
**Last Updated:** January 2025  
**Status:** Production Ready ✅  
**All Tests Passing:** ✅  
**Optimized SRTM Workflow:** ✅  
**LIDAR WGS84-First Processing:** ✅  
**Celery-Free Background Processing:** ✅  
**Database Geometry Storage:** ✅  
**Polygon Project Viewing:** ✅  
**🎉 SRTM + LIDAR UNIFIED PIPELINE:** ✅  
**PostGIS Spatial Indexing:** ✅  
**S3 Intelligent Caching:** ✅  
**Statistics Format Unification:** ✅  
**Dynamic Area Calculation:** ✅  
**LIDAR Elevation Statistics:** ✅  
**Transparency Fix:** ✅  

## 🎉 **RECENT MAJOR FIXES (January 2025):**

### **✅ Statistics Format Unification**
- **Fixed:** SRTM and LIDAR statistics now saved at root level (not nested)
- **Result:** Consistent format across all analysis types for frontend display
- **Impact:** Statistics now properly display in "My Projects" for all analyses

### **✅ Area Calculation Fix**
- **Fixed:** Dynamic area calculation using actual raster resolution instead of hard-coded 30m
- **Result:** Accurate area calculations for both SRTM (30m) and LIDAR (2m) data
- **Impact:** Proper area statistics regardless of data source resolution

### **✅ LIDAR Elevation Statistics Fix**
- **Fixed:** Enhanced NoData handling for LIDAR files with NaN values
- **Result:** LIDAR elevation statistics now calculate correctly (elevation_min, elevation_max, elevation_mean)
- **Impact:** Complete terrain statistics for LIDAR analyses

### **✅ White Buffer Transparency Fix**
- **Fixed:** Enhanced visualization logic to handle masked arrays and NaN values properly
- **Result:** No more white buffer pixels around LIDAR elevation layers
- **Impact:** Clean, professional elevation visualizations with proper transparency

### **✅ Statistics Display Consistency**
- **Fixed:** Both SRTM and LIDAR routes now save statistics at root level
- **Result:** Frontend can display statistics consistently across all analysis types
- **Impact:** Unified user experience for project viewing and statistics display

### **✅ Elevation Visualization Fix**
- **Fixed:** Vectorized color mapping with 50-color elevation ramp
- **Result:** No more black pixels, proper elevation colors with transparency
- **Impact:** Beautiful elevation visualizations for all data sources

### **✅ Bounds Format Standardization**
- **Fixed:** Unified bounds format (west/east/north/south) across all data sources
- **Result:** Frontend can properly display elevation overlays
- **Impact:** Consistent map visualization for all DEM types

### **✅ Statistics Calculation Bug Fixes**
- **Fixed:** NaN comparison bugs in statistics calculation
- **Result:** Elevation statistics now calculate correctly for all sources
- **Impact:** Complete terrain statistics in database

### **✅ Geomorphons Visualization Fix**
- **Fixed:** Comprehensive NoData handling for geomorphons visualization
- **Result:** Proper landform visualization with transparency
- **Impact:** Clean geomorphons analysis for all data sources

### **✅ Projects Database Fix**
- **Fixed:** Updated projects route to use dem_path instead of srtm_path
- **Result:** Projects page loads correctly
- **Impact:** User can view all their analysis projects

## 🚧 **NEXT PRIORITIES:**
- **Enhance Error Handling** - Improve user feedback for processing failures
- **Performance Optimization** - Further optimize parallel processing
- **Advanced Analysis** - Add more terrain analysis options


---