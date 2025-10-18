# 🚀 **Deployment Checklist for Refactored Architecture**

## 📋 **Pre-Deployment Checklist**

### **Database Migration**
- [ ] **Run migration script on staging database first**
  ```bash
  cd Backend
  python migrate_dem_schema.py
  ```
- [ ] **Verify migration idempotency** - Run migration script twice, ensure no errors
- [ ] **Check existing data integrity** - Verify all existing analyses still load correctly
- [ ] **Backup production database** before running migration

### **Code Validation**
- [ ] **Run comprehensive tests**
  ```bash
  cd Backend
  python -m pytest tests/test_refactoring.py -v
  ```
- [ ] **Test all three pipelines end-to-end**
  - [ ] SRTM pipeline: `POST /process_polygon` with SRTM data
  - [ ] LIDAR PT pipeline: `POST /api/lidar/process` with Portugal polygon
  - [ ] LIDAR USA pipeline: `POST /api/usgs-dem/process` with US polygon
- [ ] **Verify no import errors**
  ```bash
  python -c "from services.dem_processor import process_dem_files; print('✅ Imports OK')"
  ```

### **Configuration Validation**
- [ ] **Check DEM source configurations**
  ```bash
  python -c "from config.dem_sources import get_all_supported_sources; print(get_all_supported_sources())"
  ```
- [ ] **Verify cache directories exist and are writable**
  - [ ] `/app/data/srtm/` (SRTM cache)
  - [ ] `/app/data/LidarPt/` (LIDAR PT cache)
  - [ ] `/app/data/LidarUSA/` (LIDAR USA cache)

### **Performance Testing**
- [ ] **Monitor memory usage with large LIDAR datasets**
  - Test with 500MB+ LIDAR files
  - Verify no memory leaks
- [ ] **Check processing times**
  - SRTM: Should be fast (< 30s for typical polygons)
  - LIDAR PT: May be slower due to reprojection
  - LIDAR USA: Should be moderate speed
- [ ] **Test concurrent processing**
  - Multiple users processing different polygons simultaneously

## 🔍 **Post-Deployment Validation**

### **API Endpoint Testing**
- [ ] **Test all endpoints return correct responses**
  ```bash
  # Test SRTM
  curl -X POST http://localhost:5000/process_polygon \
    -H "Content-Type: application/json" \
    -d '{"polygon": {...}, "polygon_id": "test_srtm"}'
  
  # Test LIDAR PT
  curl -X POST http://localhost:5000/api/lidar/process \
    -H "Content-Type: application/json" \
    -d '{"polygon": {...}, "polygon_id": "test_lidar"}'
  
  # Test LIDAR USA
  curl -X POST http://localhost:5000/api/usgs-dem/process \
    -H "Content-Type: application/json" \
    -d '{"polygon": {...}, "polygon_id": "test_usgs"}'
  ```

### **Database Validation**
- [ ] **Verify new schema is in place**
  ```sql
  SELECT column_name FROM information_schema.columns 
  WHERE table_name = 'analyses' AND column_name = 'dem_path';
  ```
- [ ] **Check that old srtm_path column is removed**
  ```sql
  SELECT column_name FROM information_schema.columns 
  WHERE table_name = 'analyses' AND column_name = 'srtm_path';
  -- Should return no rows
  ```
- [ ] **Test database operations**
  - [ ] Create new analysis
  - [ ] Retrieve existing analysis
  - [ ] Update analysis statistics

### **Error Handling Validation**
- [ ] **Test CRS warnings with mixed data**
  - Process polygon with files in different CRS
  - Verify warnings are logged but processing continues
- [ ] **Test source-specific error handling**
  - Simulate SRTM processing failure
  - Simulate LIDAR processing failure
  - Simulate USGS processing failure
- [ ] **Test unknown data source error**
  - Try processing with invalid data source
  - Verify appropriate error message

### **Logging and Monitoring**
- [ ] **Check logs for performance metrics**
  ```bash
  grep "DEM processing completed in" logs/app.log
  ```
- [ ] **Verify CRS warnings are logged**
  ```bash
  grep "CRS" logs/app.log
  ```
- [ ] **Check data source configuration logging**
  ```bash
  grep "configuration:" logs/app.log
  ```

## 🚨 **Rollback Plan**

### **If Issues Occur**
1. **Database Rollback**
   ```sql
   -- Add back srtm_path column
   ALTER TABLE analyses ADD COLUMN srtm_path TEXT;
   
   -- Copy data back
   UPDATE analyses SET srtm_path = dem_path WHERE dem_path IS NOT NULL;
   
   -- Drop dem_path column
   ALTER TABLE analyses DROP COLUMN dem_path;
   ```

2. **Code Rollback**
   - Revert to previous commit
   - Update imports back to `services.srtm`
   - Update function calls back to `process_srtm_files`

3. **Configuration Rollback**
   - Remove `config/dem_sources.py`
   - Remove performance monitoring code

## 📊 **Success Metrics**

### **Performance Targets**
- [ ] **SRTM processing**: < 30 seconds for typical polygons
- [ ] **LIDAR PT processing**: < 2 minutes for typical polygons
- [ ] **LIDAR USA processing**: < 1 minute for typical polygons
- [ ] **Memory usage**: < 1GB peak for large datasets

### **Quality Targets**
- [ ] **Error rate**: < 1% of processing requests
- [ ] **CRS warnings**: Logged but don't cause failures
- [ ] **Data integrity**: 100% of successful processes produce valid results

## 🎯 **Post-Deployment Tasks**

### **Documentation Updates**
- [ ] Update API documentation with new field names
- [ ] Update frontend team about response structure changes
- [ ] Update deployment documentation

### **Monitoring Setup**
- [ ] Set up alerts for processing failures
- [ ] Monitor performance metrics
- [ ] Track CRS warning frequency

### **Cleanup Tasks**
- [ ] Remove old `services/srtm.py` file (after confirming no dependencies)
- [ ] Update any external documentation
- [ ] Archive old migration scripts

## ✅ **Final Validation**

- [ ] **All tests pass**
- [ ] **All three pipelines work end-to-end**
- [ ] **Database migration successful**
- [ ] **Performance within targets**
- [ ] **Error handling working correctly**
- [ ] **Logging and monitoring active**

**🎉 Deployment Complete!**
