"""
Services for downloading and processing SRTM elevation data
"""
import os
import zipfile
import logging
import numpy as np
import requests
import rasterio
from rasterio.mask import mask
from shapely.geometry import shape
from pathlib import Path

from utils.config import EARTHDATA_USERNAME, EARTHDATA_PASSWORD, SAVE_DIRECTORY

logger = logging.getLogger(__name__)

# Set up NASA Earthdata Login connection
class SessionWithHeaderRedirection(requests.Session):
    AUTH_HOST = 'urs.earthdata.nasa.gov'

    def __init__(self, username, password):
        super().__init__()
        self.auth = (username, password)

    def rebuild_auth(self, prepared_request, response):
        headers = prepared_request.headers
        url = prepared_request.url

        if 'Authorization' in headers:
            original_parsed = requests.utils.urlparse(response.request.url)
            redirect_parsed = requests.utils.urlparse(url)

            if (original_parsed.hostname != redirect_parsed.hostname) and \
                    redirect_parsed.hostname != self.AUTH_HOST and \
                    original_parsed.hostname != self.AUTH_HOST:
                del headers['Authorization']

        return

# Create a session
session = SessionWithHeaderRedirection(EARTHDATA_USERNAME, EARTHDATA_PASSWORD)

def get_srtm_data(geojson_data, output_folder=None):
    """
    Determines which SRTM tiles intersect with the given polygon and downloads them.
    SRTM tiles are always stored in the SAVE_DIRECTORY/srtm folder for reuse across projects.
    
    Args:
        geojson_data: A GeoJSON object containing a polygon geometry
        output_folder: Optional folder where to save processing outputs (not SRTM tiles)
        
    Returns:
        List of paths to SRTM files (stored in the central SRTM directory)
    """
    coordinates = geojson_data['geometry']['coordinates'][0]
    lats = [coord[1] for coord in coordinates]
    lons = [coord[0] for coord in coordinates]
    
    # Calculate bounds of the polygon
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    
    logger.info(f"Polygon bounds: lat {min_lat} to {max_lat}, lon {min_lon} to {max_lon}")
    
    # Add a small buffer
    buffer = 0.1  # About 10km
    min_lat -= buffer
    max_lat += buffer
    min_lon -= buffer
    max_lon += buffer
    
    # SRTM tiles are named by their southwest corner
    # Calculate which 1-degree tiles we need
    # Floor for minimum (southwest corner)
    min_lat_tile = int(np.floor(min_lat))
    min_lon_tile = int(np.floor(min_lon))
    
    # Ceil for maximum (to include all tiles that intersect)
    max_lat_tile = int(np.ceil(max_lat)) - 1
    max_lon_tile = int(np.ceil(max_lon)) - 1
    
    logger.info(f"Tile bounds: lat {min_lat_tile} to {max_lat_tile}, lon {min_lon_tile} to {max_lon_tile}")
    
    # Generate list of required tiles
    lat_tiles = range(min_lat_tile, max_lat_tile + 1)
    lon_tiles = range(min_lon_tile, max_lon_tile + 1)
    
    tiles_to_download = []
    for lat in lat_tiles:
        for lon in lon_tiles:
            # SRTM naming convention uses N/S and E/W prefixes
            ns = 'S' if lat < 0 else 'N'
            ew = 'W' if lon < 0 else 'E'
            lat_str = f"{abs(lat):02d}"
            lon_str = f"{abs(lon):03d}"
            tile_name = f"{ns}{lat_str}{ew}{lon_str}"
            tiles_to_download.append((lat, lon, tile_name))
    
    logger.info(f"Tiles to download: {[t[2] for t in tiles_to_download]}")
    
    # Download the identified tiles (stored in central SRTM directory)
    srtm_files = []
    for lat, lon, tile_name in tiles_to_download:
        # output_folder is ignored for SRTM tiles - they always go to SAVE_DIRECTORY/srtm
        srtm_file = download_srtm(lat, lon, output_folder=None)
        if srtm_file:
            srtm_files.append(srtm_file)
            logger.info(f"Successfully downloaded or found {tile_name}")
        else:
            logger.warning(f"Failed to download {tile_name}")
    
    return srtm_files

def download_srtm(lat, lon, output_folder=None):
    """
    Downloads an SRTM tile for the given lat/lon coordinates.
    
    Args:
        lat: Latitude of the southwest corner of the tile
        lon: Longitude of the southwest corner of the tile
        output_folder: Optional folder where to save temporary processing files (not used for SRTM tiles)
        
    Returns:
        Path to the downloaded .hgt file or None if download failed
    """
    # SRTM tile naming convention: 
    # - N/S prefix for latitude (N for >= 0, S for < 0)
    # - E/W prefix for longitude (E for >= 0, W for < 0)
    # - 2-digit absolute latitude
    # - 3-digit absolute longitude
    ns = 'S' if lat < 0 else 'N'
    ew = 'W' if lon < 0 else 'E'
    lat_str = f"{abs(int(lat)):02d}"
    lon_str = f"{abs(int(lon)):03d}"
    
    filename = f"{ns}{lat_str}{ew}{lon_str}.SRTMGL1.hgt.zip"
    hgt_filename = f"{ns}{lat_str}{ew}{lon_str}.SRTMGL1.hgt"
    logger.info(f"Looking for SRTM tile: {hgt_filename}")
    
    # Define SRTM directory - this is where all SRTM tiles are stored
    srtm_dir = os.path.join(SAVE_DIRECTORY, "srtm")
    os.makedirs(srtm_dir, exist_ok=True)
    
    # Define paths for the SRTM file
    local_zip = os.path.join(srtm_dir, filename)
    local_hgt = os.path.join(srtm_dir, hgt_filename)
    
    # Check if file already exists in the SRTM directory
    if os.path.exists(local_hgt):
        logger.info(f"File {local_hgt} already exists in SRTM directory. Using existing file.")
        return str(local_hgt)
    
    # If file doesn't exist, download it
    logger.info(f"SRTM tile not found in cache. Downloading: {hgt_filename}")
    
    urls = [
        f"https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/2000.02.11/{filename}",
        f"https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/{filename}"
    ]
    
    for url in urls:
        try:
            logger.info(f"Attempting to download: {url}")
            response = session.get(url, stream=True)
            response.raise_for_status()
            
            with open(local_zip, 'wb') as fd:
                for chunk in response.iter_content(chunk_size=1024*1024):
                    fd.write(chunk)
            
            # Extract the HGT file from the ZIP
            with zipfile.ZipFile(local_zip, 'r') as zip_ref:
                zip_contents = zip_ref.namelist()
                hgt_file = next((f for f in zip_contents if f.endswith('.hgt')), None)
                if hgt_file:
                    # Always extract to the SRTM directory
                    zip_ref.extract(hgt_file, srtm_dir)
                    
                    # Make sure the extracted file has the correct name
                    hgt_path = os.path.join(srtm_dir, hgt_file)
                    if os.path.basename(hgt_path) != os.path.basename(local_hgt):
                        os.rename(hgt_path, local_hgt)
                else:
                    raise ValueError(f"No .hgt file found in the zip archive {filename}")
            
            # Clean up the zip file
            os.remove(local_zip)
            
            if os.path.exists(local_hgt):
                logger.info(f"Downloaded and extracted {filename} to {local_hgt}")
                return str(local_hgt)
            else:
                logger.error(f"File {local_hgt} not found after extraction")
        except Exception as e:
            logger.error(f"Error downloading {filename} from {url}: {str(e)}")
            if os.path.exists(local_zip):
                os.remove(local_zip)
    
    return None

def process_srtm_files(srtm_files, geojson_data, output_folder=None):
    """
    Process SRTM files to create a merged and clipped raster for the polygon area.
    This function takes SRTM tiles (typically from the central SRTM directory)
    and creates processed outputs in the specified output_folder.
    
    Args:
        srtm_files: List of SRTM .hgt files to process (paths to files in SAVE_DIRECTORY/srtm)
        geojson_data: GeoJSON data defining the area of interest
        output_folder: Folder path where to save the resulting processed files
        
    Returns:
        dict: Processed data including the image as base64 and metadata
    """
    try:
        # If no output folder specified, use current directory
        if output_folder is None:
            output_folder = os.getcwd()
        else:
            # Ensure the output folder exists
            os.makedirs(output_folder, exist_ok=True)
            
        logger.info(f"Using output folder for SRTM processing: {output_folder}")
        
        # Define paths for temporary files
        temp_mosaic_path = os.path.join(output_folder, "temp_mosaic.tif")
        clipped_srtm_path = os.path.join(output_folder, "clipped_srtm.tif")
        
        # Convert GeoJSON to shapely geometry - this is the exact user-drawn polygon
        polygon = shape(geojson_data['geometry'])
        
        # We'll use the exact polygon for masking, without additional buffer
        # A tiny buffer (0.0001) prevents potential geometry issues but doesn't visibly change the outline
        clipping_polygon = polygon.buffer(0.0001)
        
        # Log geometry bounds
        logger.info(f"Clipping to exact polygon bounds: {polygon.bounds}")
        
        # Open SRTM files and log their bounds
        src_files_to_mosaic = []
        for file in srtm_files:
            try:
                src = rasterio.open(file)
                src_files_to_mosaic.append(src)
                logger.info(f"SRTM file {file} bounds: {src.bounds}")
            except Exception as e:
                logger.error(f"Error opening {file}: {str(e)}")
        
        if not src_files_to_mosaic:
            logger.error("No valid SRTM files to process")
            return None
            
        # Create mosaic of all SRTM tiles
        from rasterio.merge import merge
        mosaic, out_trans = merge(src_files_to_mosaic)
        logger.info(f"Mosaic shape: {mosaic.shape}")
        
        # Save mosaic to temporary file
        with rasterio.open(temp_mosaic_path, 'w', driver='GTiff',
                        height=mosaic.shape[1], width=mosaic.shape[2],
                        count=1, dtype=mosaic.dtype,
                        crs=src_files_to_mosaic[0].crs,
                        transform=out_trans) as dst:
            dst.write(mosaic[0], 1)
        
        # Mask to the exact polygon shape
        try:
            with rasterio.open(temp_mosaic_path) as src:
                logger.info(f"Mosaic bounds: {src.bounds}")
                # Create a list with the exact polygon geometry for mask operation
                geometries = [clipping_polygon]
                
                # Set crop=True to crop to the polygon bounds
                # all_touched=False to only include pixels where the center is within the polygon
                # Note: Using False here makes the mask more precise but might cause small gaps at the edges
                out_image, out_transform = mask(src, geometries, crop=True, all_touched=False, nodata=-9999)
                
                # Set all pixels outside the polygon to nodata value
                out_meta = src.meta.copy()
                out_meta.update({
                    "driver": "GTiff",
                    "height": out_image.shape[1],
                    "width": out_image.shape[2],
                    "transform": out_transform,
                    "nodata": -9999  # Set a nodata value
                })
                
                # Write the masked raster
                with rasterio.open(clipped_srtm_path, "w", **out_meta) as dest:
                    dest.write(out_image)
                
                # Read the clipped data for visualization
                with rasterio.open(clipped_srtm_path) as clipped_src:
                    data = clipped_src.read(1)
                    bounds = clipped_src.bounds
                    nodata = clipped_src.nodata
                    logger.info(f"Final clipped raster bounds: {bounds}")
                    logger.info(f"Final clipped raster shape: {data.shape}")
                
                # Create a masked array to ignore nodata values
                data_masked = np.ma.masked_where(data == nodata, data)
                data_min, data_max = np.nanmin(data_masked), np.nanmax(data_masked)
                logger.info(f"Elevation range: {data_min} to {data_max}")
                
                # Create a colored visualization with transparency outside the polygon
                # First normalize the data to 0-255 range for elevation
                if data_max > data_min:
                    normalized_data = ((data_masked - data_min) / (data_max - data_min) * 255).astype(np.uint8)
                else:
                    normalized_data = np.zeros_like(data, dtype=np.uint8)
                
                # Create RGBA image with transparent background
                rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
                
                # Create a colormap (grayscale inverted - white is low, black is high)
                # Assign RGB values based on normalized elevation
                rgba[:,:,0] = 255 - normalized_data  # R
                rgba[:,:,1] = 255 - normalized_data  # G
                rgba[:,:,2] = 255 - normalized_data  # B
                
                # Set alpha channel - transparent for masked/nodata values, opaque for valid data
                rgba[:,:,3] = np.where(data_masked.mask, 0, 255)  # Alpha
                
                # Convert to PIL Image and save as PNG (supports transparency)
                from PIL import Image
                import io
                import base64
                
                img = Image.fromarray(rgba)
                
                # Save the visualization image to a file in the output folder
                visualization_path = os.path.join(output_folder, "srtm_visualization.png")
                img.save(visualization_path, format="PNG")
                logger.info(f"Saved SRTM visualization to: {visualization_path}")
                
                # Also prepare the base64 encoded version for the response
                buffered = io.BytesIO()
                img.save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()
                
                return {
                    'image': img_str,
                    'min_height': float(data_min),
                    'max_height': float(data_max),
                    'width': data.shape[1],
                    'height': data.shape[0],
                    'bounds': {
                        'north': bounds.top,
                        'south': bounds.bottom,
                        'east': bounds.right,
                        'west': bounds.left
                    },
                    'temp_mosaic_path': temp_mosaic_path,
                    'clipped_srtm_path': clipped_srtm_path,
                    'visualization_path': visualization_path
                }
        except Exception as e:
            logger.error(f"Error in polygon masking: {str(e)}", exc_info=True)
            return None
            
    except Exception as e:
        logger.error(f"Error processing SRTM files: {str(e)}", exc_info=True)
        return None 