# 🔍 **LIDAR DEM Workflow Analysis**

## 📋 **Complete Workflow Investigation**

Based on code analysis, here's the **complete LIDAR DEM workflow**:

## 🎯 **1. ENTRY POINT: `/api/lidar/process` Route**

**File:** `Backend/routes/lidar.py:134-236`

**Input:** 
- `polygon_geometry`: GeoJSON polygon in WGS84
- `polygon_id`: Unique identifier

**Process:**
```python
# PHASE 1: LIDAR-specific preparation
clipped_lidar_path = process_lidar_dem(polygon_geometry, polygon_id)

# PHASE 2: Unified analysis & visualization  
results = process_srtm_files(polygon_geometry, clipped_lidar_path, output_dir, polygon_id)

# PHASE 3: Database storage
db_service.save_analysis_results(polygon_id, analysis_data)
```

---

## 🏗️ **2. LIDAR PROCESSOR: `process_lidar_dem()`**

**File:** `Backend/services/lidar_processor.py:75-140`

### **Step 1: CRS Conversion for Spatial Query**
```python
# Convert WGS84 → ETRS89/TM06 (EPSG:3763)
etrs89_polygon = self._convert_polygon_to_etrs89(polygon_geometry)
```
- ✅ **Purpose:** LIDAR tiles are in EPSG:3763, need same CRS for spatial query
- ✅ **Method:** `_convert_polygon_to_etrs89()` uses `gpd.to_crs()`
- ✅ **Output:** GeoDataFrame in EPSG:3763

### **Step 2: PostGIS Spatial Query**
```python
intersecting_tiles = self._find_intersecting_tiles(etrs89_polygon)
```
- ✅ **Purpose:** Find which LIDAR tiles intersect with polygon
- ✅ **Method:** `_find_intersecting_tiles_s3()` queries PostGIS table
- ✅ **Query:** `SELECT name, s3_path FROM lidarpt2m2025tiles WHERE ST_Intersects(geometry, ST_GeomFromText(%s, 3763))`
- ✅ **Output:** List of S3 paths (e.g., `["MDT-2m/MDT-2m-202258-04-2024.tif"]`)

### **Step 3: S3 Download with Caching**
```python
for s3_path in intersecting_tiles:
    local_path = self._download_tile_from_s3(s3_path)
```
- ✅ **Purpose:** Download S3 tiles to local storage
- ✅ **Method:** `_download_tile_from_s3()` with 7-day cache
- ✅ **Cache Location:** `/app/data/LidarPt/`
- ✅ **Output:** Local file paths (e.g., `["/app/data/LidarPt/MDT-2m-202258-04-2024.tif"]`)

### **Step 4: Tile Processing**
```python
if len(local_tile_paths) == 1:
    merged_etrs89_path = local_tile_paths[0]  # Single tile
else:
    merged_etrs89_path = self._merge_lidar_tiles(local_tile_paths, polygon_id)  # Multiple tiles
```
- ✅ **Purpose:** Handle single or multiple tiles
- ✅ **Output:** Single ETRS89/TM06 file path

### **Step 5: CRS Reprojection**
```python
wgs84_dem_path = self._reproject_to_wgs84(merged_etrs89_path, polygon_id)
```
- ✅ **Purpose:** Convert ETRS89/TM06 → WGS84 for final output
- ✅ **Method:** `_reproject_to_wgs84()` uses `rasterio.warp.reproject()`
- ✅ **Output:** WGS84 GeoTIFF in `/tmp/lidar_wgs84_{polygon_id}/`

### **Step 6: Polygon Clipping**
```python
clipped_lidar_path = self._clip_lidar_dem(wgs84_dem_path, polygon_geometry, polygon_id)
```
- ✅ **Purpose:** Clip WGS84 DEM with original WGS84 polygon
- ✅ **Method:** `_clip_lidar_dem()` uses `rasterio.mask.mask()`
- ✅ **Output:** `/app/data/polygon_sessions/{polygon_id}/{polygon_id}_lidar.tif`
- ✅ **CRS:** WGS84 (EPSG:4326)

### **Step 7: Cleanup**
```python
self._cleanup_temp_files([merged_etrs89_path, wgs84_dem_path], polygon_id)
```
- ✅ **Purpose:** Remove temporary files
- ✅ **Keeps:** Final clipped file in polygon_sessions

---

## 🎨 **3. UNIFIED VISUALIZATION: `process_srtm_files()`**

**File:** `Backend/services/srtm.py:202-456`

**Input:** 
- `polygon_geometry`: Original WGS84 polygon
- `clipped_lidar_path`: Clipped LIDAR DEM file path
- `output_folder`: `/app/data/polygon_sessions/{polygon_id}`

**Process:**
```python
# Uses the clipped LIDAR file as input (not SRTM files)
# Applies same visualization logic as SRTM
# Creates elevation visualization with topographic color ramp
# Generates statistics and bounds
```

**Output:**
- ✅ **Image:** Base64 encoded elevation visualization
- ✅ **Bounds:** Clipped raster bounds (not original polygon bounds)
- ✅ **Statistics:** Elevation statistics
- ✅ **File Path:** `clipped_srtm_path` (points to LIDAR file)

---

## 💾 **4. DATABASE STORAGE: `save_analysis_results()`**

**File:** `Backend/services/database.py:158-200`

**Database Fields:**
```sql
INSERT INTO analyses (
    id, polygon_id, user_id, 
    srtm_path,           -- Points to clipped LIDAR file
    slope_path,          -- NULL (not generated)
    aspect_path,         -- NULL (not generated) 
    contours_path,       -- NULL (not generated)
    final_dem_path,      -- NULL (not used for LIDAR)
    data_source,         -- 'lidar'
    statistics,          -- Elevation statistics
    created_at, updated_at
)
```

---

## 🎯 **5. CRITICAL ANALYSIS: What's Working vs. Missing**

### ✅ **WORKING COMPONENTS:**

1. **PostGIS Spatial Index** - Lightning-fast tile discovery
2. **S3 Integration** - Dynamic file discovery with caching
3. **CRS Transformations** - WGS84 ↔ ETRS89/TM06 conversions
4. **Polygon Clipping** - Proper WGS84 polygon clipping
5. **File Organization** - Correct polygon_sessions structure
6. **Database Storage** - Analysis results saved to Neon DB

### 🚨 **POTENTIAL ISSUES:**

1. **File Path Confusion:**
   - LIDAR saves to: `/app/data/polygon_sessions/{polygon_id}/{polygon_id}_lidar.tif`
   - SRTM pipeline expects: `clipped_srtm_path` 
   - **Issue:** SRTM pipeline might be looking for wrong file name

2. **CRS Consistency:**
   - ✅ Polygon conversion: WGS84 → ETRS89 (for query)
   - ✅ Tile reprojection: ETRS89 → WGS84 (for clipping)
   - ✅ Clipping: WGS84 polygon + WGS84 DEM
   - ✅ **All CRS operations are correct**

3. **Database Field Mapping:**
   - LIDAR saves to `srtm_path` field (confusing naming)
   - `final_dem_path` is NULL (not used)
   - **Issue:** Field naming doesn't reflect LIDAR usage

---

## 🔧 **IDENTIFIED PROBLEM:**

The **most likely issue** is in the **file path handling** between LIDAR processor and SRTM pipeline:

1. **LIDAR saves:** `/app/data/polygon_sessions/{polygon_id}/{polygon_id}_lidar.tif`
2. **SRTM expects:** `/app/data/polygon_sessions/{polygon_id}/clipped_srtm.tif`

**The SRTM pipeline is looking for `clipped_srtm.tif` but LIDAR creates `{polygon_id}_lidar.tif`!**

---

## 🎯 **RECOMMENDED FIX:**

Update the LIDAR processor to save the file with the expected name:

```python
# In _clip_lidar_dem method:
clipped_path = os.path.join(output_dir, "clipped_srtm.tif")  # Instead of f"{polygon_id}_lidar.tif"
```

This ensures the SRTM pipeline finds the file it expects! 🎯
