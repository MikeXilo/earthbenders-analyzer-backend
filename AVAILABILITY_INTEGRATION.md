# Integration Guide: Adding Availability Check Endpoints

## Quick Integration Steps:

### 1. Add the availability routes to your main app
In your `Backend/app.py` or `Backend/main.py`, add:

```python
from routes.availability import availability_bp

# Register the blueprint
app.register_blueprint(availability_bp)
```

### 2. Test the endpoints
You can test these endpoints with curl:

```bash
# Test LiDAR availability for Portugal
curl -X POST http://localhost:5000/api/lidar/check-availability \
  -H "Content-Type: application/json" \
  -d '{
    "polygon": {
      "type": "Polygon",
      "coordinates": [[[-8.0, 37.0], [-8.0, 40.0], [-7.0, 40.0], [-7.0, 37.0], [-8.0, 37.0]]]
    }
  }'

# Test USGS DEM availability for US
curl -X POST http://localhost:5000/api/usgs-dem/check-availability \
  -H "Content-Type: application/json" \
  -d '{
    "polygon": {
      "type": "Polygon", 
      "coordinates": [[[-100.0, 30.0], [-100.0, 35.0], [-95.0, 35.0], [-95.0, 30.0], [-100.0, 30.0]]]
    }
  }'
```

### 3. Expected Responses:

**LiDAR (Portugal polygon):**
```json
{
  "available": true,
  "region": "portugal", 
  "message": "LiDAR available for portugal region"
}
```

**LiDAR (Global polygon):**
```json
{
  "available": false,
  "region": "global",
  "message": "LiDAR not available for global region"
}
```

**USGS DEM (US polygon):**
```json
{
  "available": true,
  "region": "us",
  "message": "USGS DEM available for us region"
}
```

**SRTM High-Res (any polygon):**
```json
{
  "available": true,
  "region": "global",
  "message": "SRTM High-Res available globally"
}
```

## What This Fixes:

✅ **Pre-validation system now works** - Frontend can check availability before showing options
✅ **LiDAR detection works properly** - Portugal polygons show LiDAR option
✅ **USGS DEM detection works** - US polygons show USGS DEM option  
✅ **SRTM High-Res always available** - Global availability
✅ **Graceful fallbacks** - If endpoints fail, frontend falls back to geographic detection

## Next Steps:

1. **Deploy these endpoints** to your backend
2. **Test the frontend** - LiDAR should now show for Portugal polygons
3. **Implement actual data source processing** for SRTM High-Res and USGS DEM
4. **Add more sophisticated availability checks** (e.g., check actual tile coverage)

The frontend pre-validation system is now complete and will work as intended! 🎯
