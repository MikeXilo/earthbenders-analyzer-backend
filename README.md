# Basemap Backend

Backend deployment for the Basemap platform - handles SRTM data processing and terrain analysis.

## Deployment

This repository is automatically deployed to Railway. The backend provides:

- Polygon saving and processing
- SRTM data download and processing
- Terrain analysis tools
- Vector tile serving

## Environment Variables

Set these in Railway dashboard:

- `EARTHDATA_USERNAME`: NASA Earthdata username
- `EARTHDATA_PASSWORD`: NASA Earthdata password  
- `CORS_ORIGIN`: Frontend domain (e.g., https://your-app.vercel.app)
- `DEBUG`: false (for production)
- `IS_DOCKER`: true

## Data Management

- SRTM files are downloaded on-demand to `/app/data/srtm/`
- Processed data is saved to `/app/data/polygon_sessions/`
- Data persists across deployments

## API Endpoints

- `POST /save_polygon` - Save polygon data
- `POST /process_polygon` - Process SRTM data for polygon
- `POST /centroid` - Calculate polygon centroid
- `GET /health` - Health check