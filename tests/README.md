# LiDAR USA Test Suite

This directory contains tests for LiDAR USA functionality, including USGS 3DEP DEM download and processing.

## Test Files

### `test_usgs_dem_simple.py`
Focused test for USGS DEM download functionality:
- Downloads DEM tiles for 3 US regions
- Validates downloaded files
- Saves files to `tests/data` directory
- Provides detailed statistics

## Test Data Directory

The `tests/data` directory stores downloaded DEM tiles:
- **California (Los Angeles)**: `usgs_3dep_california_-118.2500_34.0500_-118.2000_34.1000.tif`
- **New York (Manhattan)**: `usgs_3dep_new_york_-74.0000_40.7000_-73.9500_40.7500.tif`
- **Texas (Austin)**: `usgs_3dep_texas_-97.8000_30.2000_-97.7500_30.2500.tif`

Each file is approximately 4.2 MB and contains high-resolution elevation data.

## Running Tests

### USGS DEM Download Test
```bash
cd Backend
python tests/test_usgs_dem_simple.py
```

## Test Results

### Test Results
- ✅ All 3 USGS DEM downloads successful
- ✅ File validation successful
- ✅ Files saved to tests/data directory

## Test Coordinates

The tests use real-world coordinates for different US regions:

1. **Los Angeles, CA**: -118.25, 34.05, -118.2, 34.1
2. **Manhattan, NY**: -74.0, 40.7, -73.95, 40.75  
3. **Austin, TX**: -97.8, 30.2, -97.75, 30.25

## Elevation Data Quality

The downloaded DEM files contain high-quality elevation data:

- **California**: 74-257 meters elevation range
- **New York**: -13 to 27 meters elevation range (includes sea level)
- **Texas**: 147-226 meters elevation range

All files are in WGS84 coordinate system with 1000x1000 pixel resolution.

## Integration Notes

The tests validate the complete LiDAR USA processing pipeline:
1. USGS 3DEP DEM download via ArcGIS Image Server
2. Coordinate system handling (WGS84)
3. File storage and caching
4. Integration with existing backend services

The downloaded DEM tiles can be used for further testing and development of the LiDAR processing pipeline.
