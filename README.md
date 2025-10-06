# Earthbenders Analyzer Backend

A Flask-based geospatial analysis backend that processes polygon data, generates terrain analysis, and manages file storage with database integration.

## 🏗️ Architecture

### **Database Layer (Neon PostgreSQL)**
- **Polygon metadata** - Bounds, status, user associations
- **Analysis results** - SRTM processing, slope analysis, contours
- **File tracking** - Metadata for all generated files
- **User management** - Ready for future authentication

### **File Storage (Railway Volumes)**
- **GeoJSON files** - User-drawn polygons
- **SRTM data** - Clipped terrain elevation data
- **Processed outputs** - Slope, contours, analysis results
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
- **Database Integration:** Neon PostgreSQL fully operational
- **File Storage:** Railway volumes working correctly
- **SRTM Processing:** Real-world terrain data processing functional
- **API Endpoints:** All core operations tested and working
- **Error Handling:** Robust error management implemented

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
  }
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
    srtm_path TEXT,
    slope_path TEXT,
    bounds JSONB,
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
    elevation JSONB,
    slope JSONB,
    aspect JSONB,
    contours JSONB,
    statistics JSONB,
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
backend/
├── server.py                 # Main Flask application
├── create_tables.py          # Database table creation script
├── requirements.txt          # Python dependencies
├── Dockerfile               # Container configuration
├── railway.json             # Railway deployment config
├── Procfile                 # Alternative start command
├── services/
│   ├── database.py          # Database service layer
│   ├── srtm.py             # SRTM data processing
│   ├── terrain.py          # Terrain analysis
│   └── water_accumulation.py # Water flow analysis
├── routes/
│   ├── core.py             # Core API routes
│   └── polygon.py          # Polygon operations
├── utils/
│   ├── config.py           # Configuration settings
│   └── file_io.py          # File I/O operations
└── data/                   # File storage directory
    ├── polygon_sessions/   # User polygon files
    ├── srtm/               # SRTM elevation data
    └── basemaps/           # Base map data
```

## 🔄 Data Flow

1. **User draws polygon** → Frontend sends GeoJSON to `/save_polygon`
2. **Backend saves metadata** → Stores in Neon database
3. **Backend saves file** → Stores GeoJSON in Railway volume
4. **User requests processing** → Calls `/process_polygon`
5. **Backend fetches SRTM** → Downloads elevation data
6. **Backend processes data** → Clips and analyzes terrain
7. **Backend saves results** → Stores files and metadata
8. **Database tracks status** → Updates polygon status and results

### **Recent Fixes & Improvements**
- **GeoJSON Parsing:** Fixed Feature object handling in `shapely.geometry.shape()`
- **SRTM Function Calls:** Corrected parameter passing to `get_srtm_data()`
- **Database Health Check:** Improved error handling and connection management
- **Real-World Testing:** Validated with California coordinates for SRTM data
- **Error Handling:** Enhanced logging and graceful failure management

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

**Version:** 6.1  
**Last Updated:** January 2025  
**Status:** Production Ready ✅  
**All Tests Passing:** ✅