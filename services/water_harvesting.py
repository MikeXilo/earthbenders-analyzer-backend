"""
Water Harvesting Potential Calculator Service
Uses real climate data and soil properties for accurate calculations
"""

import requests
import logging
from datetime import datetime
from shapely.geometry import shape
from pyproj import Geod

logger = logging.getLogger(__name__)


class WaterHarvestingService:
    """
    Calculate water harvesting potential using:
    - Real rainfall data (Open-Meteo API - FREE)
    - Soil texture (SoilGrids API - FREE, with classification fallback)
    - Slope analysis in PERCENT (from DEM)
    - Area calculation (from polygon)
    """
    
    def calculate_water_harvesting_potential(
        self, 
        polygon_geometry, 
        polygon_id, 
        average_slope_percent,
        user_id=None
    ):
        """
        Calculate water harvesting potential with real data
        
        Args:
            polygon_geometry: GeoJSON polygon
            polygon_id: Unique polygon identifier
            average_slope_percent: Average slope in PERCENT (e.g., 12.5 for 12.5%)
            user_id: Optional user identifier
        
        Returns:
            dict: Complete water harvesting analysis
        """
        
        logger.info(f"Calculating water harvesting for polygon {polygon_id}")
        
        try:
            # 1. Calculate area
            area_m2 = self._calculate_area_m2(polygon_geometry)
            area_hectares = area_m2 / 10000
            area_acres = area_hectares * 2.471
            
            logger.info(f"Area: {area_hectares:.2f} ha ({area_acres:.2f} acres)")
            
            # 2. Get centroid for location-based queries
            centroid = self._get_centroid(polygon_geometry)
            lat, lon = centroid
            
            logger.info(f"Location: ({lat:.4f}, {lon:.4f})")
            
            # 3. Get real annual rainfall from API
            annual_rainfall_mm = self._get_annual_rainfall(lat, lon)
            
            if annual_rainfall_mm is None:
                raise Exception("Could not fetch rainfall data from any source")
            
            logger.info(f"Annual rainfall: {annual_rainfall_mm}mm")
            
            # 4. Get soil texture from API (with classification fallback)
            soil_data = self._get_soil_texture(lat, lon)
            soil_type = soil_data.get('soil_type', 'loam') if soil_data else 'loam'
            
            logger.info(f"Soil type: {soil_type}, Slope: {average_slope_percent}%")
            
            # 5. Calculate runoff coefficient
            runoff_coefficient = self._calculate_runoff_coefficient(
                average_slope_percent, 
                soil_type
            )
            
            logger.info(f"Runoff coefficient: {runoff_coefficient:.2f}")
            
            # 6. Calculate water harvest potential
            # Formula: Area (m2) x Rainfall (mm) x Runoff Coefficient = Liters
            annual_harvest_liters = area_m2 * annual_rainfall_mm * runoff_coefficient
            annual_harvest_gallons = annual_harvest_liters * 0.264172
            annual_harvest_m3 = annual_harvest_liters / 1000
            
            # 7. Generate comparisons
            comparisons = self._generate_comparisons(annual_harvest_liters, area_hectares)
            
            # 8. Generate recommendations
            recommendations = self._generate_recommendations(
                area_hectares, 
                annual_harvest_liters,
                runoff_coefficient
            )
            
            # 9. Cost analysis
            cost_analysis = self._calculate_costs(
                area_hectares, 
                annual_harvest_liters,
                average_slope_percent
            )
            
            # 10. Compile results
            results = {
                'area_hectares': round(area_hectares, 2),
                'area_acres': round(area_acres, 2),
                'area_m2': round(area_m2, 0),
                'location': {
                    'latitude': round(lat, 4),
                    'longitude': round(lon, 4)
                },
                'climate': {
                    'annual_rainfall_mm': annual_rainfall_mm,
                    'annual_rainfall_inches': round(annual_rainfall_mm / 25.4, 1)
                },
                'terrain': {
                    'average_slope_percent': round(average_slope_percent, 1),
                    'soil_type': soil_type,
                    'soil_details': soil_data
                },
                'runoff_coefficient': round(runoff_coefficient, 2),
                'harvest_potential': {
                    'annual_liters': round(annual_harvest_liters, 0),
                    'annual_gallons': round(annual_harvest_gallons, 0),
                    'annual_m3': round(annual_harvest_m3, 0),
                    'daily_liters': round(annual_harvest_liters / 365, 0),
                    'monthly_liters': round(annual_harvest_liters / 12, 0)
                },
                'comparisons': comparisons,
                'recommendations': recommendations,
                'cost_analysis': cost_analysis
            }
            
            # 11. Save to database
            if polygon_id:
                self._save_water_harvesting_results(polygon_id, user_id, results)
                logger.info(f"Results saved to database for polygon {polygon_id}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error calculating water harvesting: {str(e)}")
            raise
    
    def _get_annual_rainfall(self, lat, lon):
        """
        Get real annual rainfall from free APIs
        Tries Open-Meteo first, falls back to NASA POWER
        """
        
        # Try Open-Meteo (best option)
        rainfall = self._get_rainfall_open_meteo(lat, lon, years=10)
        if rainfall is not None:
            return rainfall
        
        # Fallback to NASA POWER
        logger.warning("Open-Meteo failed, trying NASA POWER...")
        rainfall = self._get_rainfall_nasa_power(lat, lon)
        if rainfall is not None:
            return rainfall
        
        # Final fallback: Climate zone estimate
        logger.warning("All APIs failed, using climate zone estimate")
        return self._estimate_rainfall_by_zone(lat, lon)
    
    def _get_rainfall_open_meteo(self, lat, lon, years=10):
        """
        Get rainfall from Open-Meteo Historical Weather API
        FREE, no API key required!
        """
        
        try:
            current_year = datetime.now().year
            start_year = current_year - years
            
            url = "https://archive-api.open-meteo.com/v1/archive"
            
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": f"{start_year}-01-01",
                "end_date": f"{current_year - 1}-12-31",
                "daily": "precipitation_sum",
                "timezone": "auto"
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Sum all daily precipitation
            daily_precip = data['daily']['precipitation_sum']
            total_precip = sum([p for p in daily_precip if p is not None])
            
            # Calculate annual average
            num_years = len(daily_precip) / 365.25
            annual_rainfall = total_precip / num_years
            
            logger.info(f"Open-Meteo: {annual_rainfall:.1f}mm/year (avg of {years} years)")
            
            return round(annual_rainfall, 1)
            
        except Exception as e:
            logger.error(f"Open-Meteo API error: {e}")
            return None
    
    def _get_rainfall_nasa_power(self, lat, lon):
        """
        Get rainfall from NASA POWER API
        FREE, no API key required!
        """
        
        try:
            url = "https://power.larc.nasa.gov/api/temporal/climatology/point"
            
            params = {
                "parameters": "PRECTOTCORR",
                "community": "AG",
                "longitude": lon,
                "latitude": lat,
                "format": "JSON"
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Get monthly precipitation (mm/day)
            monthly_precip = data['properties']['parameter']['PRECTOTCORR']
            
            # Convert to annual (mm/year)
            days_per_month = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            annual_rainfall = sum([
                monthly_precip[str(month)] * days
                for month, days in enumerate(days_per_month, 1)
            ])
            
            logger.info(f"NASA POWER: {annual_rainfall:.1f}mm/year (climatology)")
            
            return round(annual_rainfall, 1)
            
        except Exception as e:
            logger.error(f"NASA POWER API error: {e}")
            return None
    
    def _estimate_rainfall_by_zone(self, lat, lon):
        """
        Fallback: Estimate rainfall by broad climate zone
        """
        
        # Mediterranean (Portugal, Spain, Greece, Southern California)
        if 30 <= lat <= 45 and -10 <= lon <= 45:
            return 600
        
        # Northern Europe (UK, Germany, France)
        elif 45 <= lat <= 60 and -10 <= lon <= 30:
            return 800
        
        # Tropical (equatorial regions)
        elif -23.5 <= lat <= 23.5:
            return 1800
        
        # Arid/Desert regions
        elif abs(lat) < 35 and (lon < -100 or (20 <= lon <= 60)):
            return 250
        
        # Default: Temperate
        else:
            return 700
    
    def _get_soil_texture(self, lat, lon):
        """
        Get soil texture from SoilGrids API
        
        Strategy:
        1. Try properties endpoint for detailed texture (clay/sand/silt %)
        2. If null, try classification endpoint for WRB soil type
        3. Map WRB type to typical texture characteristics
        """
        
        # ATTEMPT 1: Try properties endpoint (detailed texture data)
        detailed_soil = self._get_soil_properties(lat, lon)
        if detailed_soil:
            return detailed_soil
        
        # ATTEMPT 2: Try classification endpoint (WRB soil type)
        logger.info("Properties endpoint returned null, trying classification endpoint...")
        classified_soil = self._get_soil_classification(lat, lon)
        if classified_soil:
            return classified_soil
        
        # ATTEMPT 3: Fallback to default
        logger.warning("All SoilGrids endpoints failed, using default loam")
        return None
    
    def _get_soil_properties(self, lat, lon):
        """
        Try to get detailed soil properties (clay/sand/silt percentages)
        """
        
        # Try multiple depths
        depths_to_try = ["5-15cm", "0-5cm", "15-30cm"]
        
        for depth in depths_to_try:
            try:
                url = "https://rest.isric.org/soilgrids/v2.0/properties/query"
                
                params = {
                    "lon": lon,
                    "lat": lat,
                    "property": ["clay", "sand", "silt"],
                    "depth": depth,
                    "value": "mean"
                }
                
                response = requests.get(url, params=params, timeout=15)
                
                if response.status_code != 200:
                    continue
                
                data = response.json()
                properties = data['properties']['layers']
                
                clay_gkg = properties[0]['depths'][0]['values']['mean']
                sand_gkg = properties[1]['depths'][0]['values']['mean']
                silt_gkg = properties[2]['depths'][0]['values']['mean']
                
                # Check if values are null
                if clay_gkg is None or sand_gkg is None or silt_gkg is None:
                    continue
                
                # Validate values
                if not all(0 <= val <= 1000 for val in [clay_gkg, sand_gkg, silt_gkg]):
                    continue
                
                # Convert to percentage
                clay_percent = clay_gkg / 10
                sand_percent = sand_gkg / 10
                silt_percent = silt_gkg / 10
                
                soil_type = self._classify_soil_texture(clay_percent, sand_percent, silt_percent)
                
                logger.info(f"SoilGrids properties: {soil_type} at {depth} (Clay: {clay_percent:.1f}%, Sand: {sand_percent:.1f}%, Silt: {silt_percent:.1f}%)")
                
                return {
                    'clay_percent': round(clay_percent, 1),
                    'sand_percent': round(sand_percent, 1),
                    'silt_percent': round(silt_percent, 1),
                    'soil_type': soil_type,
                    'data_source': 'properties',
                    'depth': depth
                }
                
            except Exception as e:
                logger.debug(f"Properties endpoint error at depth {depth}: {e}")
                continue
        
        return None
    
    def _get_soil_classification(self, lat, lon):
        """
        Get soil classification from WRB system
        Returns estimated texture based on WRB soil type
        """
        
        try:
            url = "https://rest.isric.org/soilgrids/v2.0/classification/query"
            
            params = {
                "lon": lon,
                "lat": lat,
                "number_classes": 1  # Just get the most probable class
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            wrb_class = data.get('wrb_class_name')
            probability = data.get('wrb_class_probability', [[None, 0]])[0][1]
            
            if not wrb_class:
                return None
            
            # Map WRB classification to typical soil texture
            wrb_to_texture = self._map_wrb_to_texture(wrb_class)
            
            logger.info(f"SoilGrids classification: {wrb_class} ({probability}% probability) -> {wrb_to_texture['soil_type']}")
            
            return {
                'clay_percent': wrb_to_texture['clay_percent'],
                'sand_percent': wrb_to_texture['sand_percent'],
                'silt_percent': wrb_to_texture['silt_percent'],
                'soil_type': wrb_to_texture['soil_type'],
                'data_source': 'classification',
                'wrb_class': wrb_class,
                'wrb_probability': probability
            }
            
        except Exception as e:
            logger.error(f"Classification endpoint error: {e}")
            return None
    
    def _map_wrb_to_texture(self, wrb_class):
        """
        Map WRB soil classification to typical texture characteristics
        Based on FAO WRB soil descriptions
        """
        
        # WRB soil type -> typical texture characteristics
        wrb_texture_map = {
            'Luvisols': {
                'soil_type': 'clay_loam',
                'clay_percent': 30.0,
                'sand_percent': 35.0,
                'silt_percent': 35.0,
                'description': 'Clay accumulation in subsoil, moderate drainage'
            },
            'Vertisols': {
                'soil_type': 'clay',
                'clay_percent': 45.0,
                'sand_percent': 25.0,
                'silt_percent': 30.0,
                'description': 'Heavy clay, shrink-swell properties'
            },
            'Cambisols': {
                'soil_type': 'loam',
                'clay_percent': 20.0,
                'sand_percent': 40.0,
                'silt_percent': 40.0,
                'description': 'Young soils, moderate development'
            },
            'Fluvisols': {
                'soil_type': 'sandy_loam',
                'clay_percent': 15.0,
                'sand_percent': 55.0,
                'silt_percent': 30.0,
                'description': 'Floodplain soils, stratified'
            },
            'Leptosols': {
                'soil_type': 'loam',
                'clay_percent': 18.0,
                'sand_percent': 45.0,
                'silt_percent': 37.0,
                'description': 'Shallow soils over rock'
            },
            'Phaeozems': {
                'soil_type': 'loam',
                'clay_percent': 22.0,
                'sand_percent': 38.0,
                'silt_percent': 40.0,
                'description': 'Dark, fertile prairie soils'
            },
            'Calcisols': {
                'soil_type': 'sandy_loam',
                'clay_percent': 16.0,
                'sand_percent': 52.0,
                'silt_percent': 32.0,
                'description': 'Calcium carbonate accumulation'
            },
            'Regosols': {
                'soil_type': 'sandy_loam',
                'clay_percent': 12.0,
                'sand_percent': 60.0,
                'silt_percent': 28.0,
                'description': 'Little soil development'
            },
            'Arenosols': {
                'soil_type': 'sandy',
                'clay_percent': 8.0,
                'sand_percent': 75.0,
                'silt_percent': 17.0,
                'description': 'Sandy soils'
            },
            'Kastanozems': {
                'soil_type': 'loam',
                'clay_percent': 24.0,
                'sand_percent': 36.0,
                'silt_percent': 40.0,
                'description': 'Steppe soils with calcium accumulation'
            },
            'Lixisols': {
                'soil_type': 'clay_loam',
                'clay_percent': 32.0,
                'sand_percent': 33.0,
                'silt_percent': 35.0,
                'description': 'Strongly weathered with clay accumulation'
            },
            'Acrisols': {
                'soil_type': 'clay_loam',
                'clay_percent': 28.0,
                'sand_percent': 36.0,
                'silt_percent': 36.0,
                'description': 'Acidic with clay accumulation'
            },
            'Alisols': {
                'soil_type': 'clay_loam',
                'clay_percent': 29.0,
                'sand_percent': 35.0,
                'silt_percent': 36.0,
                'description': 'Acidic with high aluminum'
            }
        }
        
        # Return mapped texture or default to loam
        return wrb_texture_map.get(wrb_class, {
            'soil_type': 'loam',
            'clay_percent': 20.0,
            'sand_percent': 40.0,
            'silt_percent': 40.0,
            'description': 'Default balanced soil'
        })
    
    def _classify_soil_texture(self, clay, sand, silt):
        """
        Classify soil type based on USDA texture triangle
        Simplified for runoff calculations
        """
        
        if clay > 40:
            return 'clay'
        elif sand > 50:
            return 'sandy'
        elif silt > 40:
            return 'silty'
        elif clay > 27:
            return 'clay_loam'
        elif sand > 40:
            return 'sandy_loam'
        else:
            return 'loam'
    
    def _calculate_runoff_coefficient(self, avg_slope_percent, soil_type):
        """
        Calculate runoff coefficient based on slope (%) AND soil texture
        Based on USDA NRCS guidelines
        
        Args:
            avg_slope_percent: Average slope in PERCENT
            soil_type: Soil classification
        
        Returns:
            float: Runoff coefficient (0.10 to 0.95)
        """
        
        # Base coefficient from slope %
        if avg_slope_percent < 5:
            base = 0.30  # Flat (0-5%)
        elif avg_slope_percent < 15:
            base = 0.50  # Gentle (5-15%)
        elif avg_slope_percent < 30:
            base = 0.70  # Moderate (15-30%)
        else:
            base = 0.85  # Steep (>30%)
        
        # Soil texture adjustment
        soil_adjustments = {
            'clay': +0.15,
            'clay_loam': +0.08,
            'silty': +0.05,
            'loam': 0.00,
            'sandy_loam': -0.08,
            'sandy': -0.15
        }
        
        adjustment = soil_adjustments.get(soil_type, 0.00)
        coefficient = base + adjustment
        
        # Constrain to realistic range
        return max(0.10, min(0.95, coefficient))
    
    def _calculate_area_m2(self, polygon_geometry):
        """Calculate area in square meters using geodesic calculation"""
        try:
            geod = Geod(ellps="WGS84")
            poly = shape(polygon_geometry)
            area_m2, _ = geod.geometry_area_perimeter(poly)
            return abs(area_m2)
        except Exception as e:
            logger.error(f"Error calculating area: {e}")
            raise
    
    def _get_centroid(self, polygon_geometry):
        """Get centroid (lat, lon)"""
        try:
            poly = shape(polygon_geometry)
            centroid = poly.centroid
            return (centroid.y, centroid.x)  # (lat, lon)
        except Exception as e:
            logger.error(f"Error getting centroid: {e}")
            raise
    
    def _generate_comparisons(self, liters, area_hectares):
        """Generate human-readable comparisons"""
        
        olympic_pools = liters / 2500000
        households = liters / 150000  # 150k liters/year per household
        irrigated_ha = liters / 5000000  # 5M liters/ha/year for crops
        bathtubs = liters / 300  # 300 liters per bathtub
        
        return {
            'olympic_pools': round(olympic_pools, 1),
            'households_annual_use': round(households, 1),
            'irrigated_hectares': round(irrigated_ha, 1),
            'bathtubs': round(bathtubs, 0),
            'description': f"Enough water for {round(households, 1)} households for a year, or to irrigate {round(irrigated_ha, 1)} hectares of crops"
        }
    
    def _generate_recommendations(self, area_hectares, harvest_liters, runoff_coef):
        """Generate storage and usage recommendations with both tanks and ponds"""
        
        # Recommend storing 25-40% of annual harvest depending on rainfall pattern
        recommended_storage = harvest_liters * 0.30
        recommended_storage_m3 = recommended_storage / 1000
        
        # ========================================
        # OPTION 1: TANKS
        # ========================================
        tank_10k = recommended_storage / 10000
        tank_20k = recommended_storage / 20000
        
        # Tank costs
        tank_10k_cost = tank_10k * 3000  # $3000 per 10,000L tank
        tank_20k_cost = tank_20k * 5000  # $5000 per 20,000L tank
        
        # Installation for tanks
        tank_installation = 2000  # Base installation cost
        tank_plumbing = recommended_storage_m3 * 5  # $5 per m3 for plumbing
        
        total_tank_cost_10k = tank_10k_cost + tank_installation + tank_plumbing
        total_tank_cost_20k = tank_20k_cost + tank_installation + tank_plumbing
        
        # Use the cheaper tank option for comparison
        best_tank_cost = min(total_tank_cost_10k, total_tank_cost_20k)
        best_tank_option = "10000L" if total_tank_cost_10k < total_tank_cost_20k else "20000L"
        
        # ========================================
        # OPTION 2: STORAGE PONDS (1m average depth)
        # ========================================
        pond_area_m2 = recommended_storage_m3 / 1.0  # 1m depth
        pond_area_hectares = pond_area_m2 / 10000
        pond_volume_m3 = recommended_storage_m3
        
        # Calculate pond dimensions (assuming square or circular)
        pond_side_length = round(pow(pond_area_m2, 0.5), 1)  # Square pond
        pond_diameter = round(2 * pow(pond_area_m2 / 3.14159, 0.5), 1)  # Circular pond
        
        # Pond construction costs
        excavation_cost = pond_volume_m3 * 4  # $4/m3 excavation
        liner_cost = pond_area_m2 * 12  # $12/m2 for EPDM liner (optional)
        shaping_cost = pond_area_m2 * 2  # $2/m2 for shaping/compaction
        fencing_cost = (pond_side_length * 4) * 15  # $15/m fencing (safety)
        
        # Total costs
        pond_cost_with_liner = excavation_cost + liner_cost + shaping_cost + fencing_cost
        pond_cost_without_liner = excavation_cost + shaping_cost + fencing_cost
        
        # ========================================
        # COST COMPARISON
        # ========================================
        
        # Savings: Pond vs Tanks
        savings_with_liner = best_tank_cost - pond_cost_with_liner
        savings_without_liner = best_tank_cost - pond_cost_without_liner
        
        savings_percent_with_liner = (savings_with_liner / best_tank_cost * 100) if best_tank_cost > 0 else 0
        savings_percent_without_liner = (savings_without_liner / best_tank_cost * 100) if best_tank_cost > 0 else 0
        
        # Determine recommended option
        if pond_cost_without_liner < best_tank_cost:
            recommended_option = "pond_without_liner"
            recommended_cost = pond_cost_without_liner
        elif pond_cost_with_liner < best_tank_cost:
            recommended_option = "pond_with_liner"
            recommended_cost = pond_cost_with_liner
        else:
            recommended_option = "tanks"
            recommended_cost = best_tank_cost
        
        recommendations = {
            'storage': {
                'recommended_liters': round(recommended_storage, 0),
                'recommended_gallons': round(recommended_storage * 0.264172, 0),
                'recommended_m3': round(recommended_storage_m3, 0),
                
                # TANK OPTIONS
                'tank_options': {
                    '10000L_tanks': {
                        'quantity': round(tank_10k, 1),
                        'cost_per_tank': 3000,
                        'total_tank_cost': round(tank_10k_cost, 0),
                        'installation_cost': round(tank_installation + tank_plumbing, 0),
                        'total_cost': round(total_tank_cost_10k, 0)
                    },
                    '20000L_tanks': {
                        'quantity': round(tank_20k, 1),
                        'cost_per_tank': 5000,
                        'total_tank_cost': round(tank_20k_cost, 0),
                        'installation_cost': round(tank_installation + tank_plumbing, 0),
                        'total_cost': round(total_tank_cost_20k, 0)
                    },
                    'best_option': best_tank_option,
                    'best_cost': round(best_tank_cost, 0),
                    'description': f"Install {round(tank_10k if best_tank_option == '10000L' else tank_20k, 1)} tanks of {best_tank_option}"
                },
                
                # POND OPTIONS
                'pond_options': {
                    'area_m2': round(pond_area_m2, 0),
                    'area_hectares': round(pond_area_hectares, 4),
                    'depth_meters': 1.0,
                    'volume_m3': round(pond_volume_m3, 0),
                    'square_dimensions': f"{pond_side_length}m x {pond_side_length}m",
                    'circular_diameter': f"{pond_diameter}m diameter",
                    'description': f"Build ponds with a total area of {round(pond_area_m2, 0)} m2 with 1m average depth",
                    
                    # Cost breakdown
                    'costs': {
                        'excavation': round(excavation_cost, 0),
                        'liner_optional': round(liner_cost, 0),
                        'shaping_compaction': round(shaping_cost, 0),
                        'fencing': round(fencing_cost, 0),
                        'total_with_liner': round(pond_cost_with_liner, 0),
                        'total_without_liner': round(pond_cost_without_liner, 0)
                    },
                    
                    'liner_note': 'Liner (EPDM/HDPE) needed for sandy/permeable soil. Clay soils may not need liner.'
                },
                
                # COST COMPARISON
                'cost_comparison': {
                    'tanks_cost': round(best_tank_cost, 0),
                    'pond_with_liner_cost': round(pond_cost_with_liner, 0),
                    'pond_without_liner_cost': round(pond_cost_without_liner, 0),
                    
                    'savings_pond_with_liner': round(savings_with_liner, 0),
                    'savings_pond_without_liner': round(savings_without_liner, 0),
                    
                    'savings_percent_with_liner': round(savings_percent_with_liner, 1),
                    'savings_percent_without_liner': round(savings_percent_without_liner, 1),
                    
                    'recommended_option': recommended_option,
                    'recommended_cost': round(recommended_cost, 0),
                    
                    'summary': self._get_cost_comparison_summary(best_tank_cost, 
                        pond_cost_with_liner, 
                        pond_cost_without_liner,
                        savings_percent_with_liner,
                        savings_percent_without_liner
                    )
                }
            },
            'usage': {
                'irrigation_potential_hectares': round(harvest_liters / 5000000, 1),
                'households_supported': round(harvest_liters / 150000, 1),
                'livestock_capacity': round(harvest_liters / 36500, 0)  # 100L/day per large animal
            },
            'interventions': []
        }
        
        # Suggest interventions based on runoff coefficient
        if runoff_coef > 0.70:
            recommendations['interventions'].append({
                'type': 'Swales/Berms',
                'reason': 'High runoff detected - install swales to slow water and increase infiltration',
                'benefit': 'Could reduce runoff by 30-50%'
            })
        
        if runoff_coef > 0.60:
            recommendations['interventions'].append({
                'type': 'Vegetation Cover',
                'reason': 'Plant ground cover or trees to reduce runoff',
                'benefit': 'Could reduce runoff coefficient by 0.10-0.20'
            })
        
        return recommendations

    def _get_cost_comparison_summary(self, tank_cost, pond_with_liner, pond_without_liner, savings_pct_liner, savings_pct_no_liner):
        """Generate a human-readable cost comparison summary"""
        
        if pond_without_liner < tank_cost and pond_without_liner < pond_with_liner:
            return f"Pond without liner is cheapest: ${round(pond_without_liner, 0):,} (saves {abs(savings_pct_no_liner):.0f}% vs tanks). Suitable if you have clay soil with low permeability."
        
        elif pond_with_liner < tank_cost:
            return f"Pond with liner is cheaper: ${round(pond_with_liner, 0):,} (saves {abs(savings_pct_liner):.0f}% vs tanks). Recommended for sandy/permeable soils."
        
        else:
            return f"Tanks are more cost-effective: ${round(tank_cost, 0):,}. Ponds would cost ${round(pond_without_liner, 0):,} (without liner) or ${round(pond_with_liner, 0):,} (with liner). Tanks recommended for small properties or where space is limited."
    
    def _calculate_costs(self, area_hectares, harvest_liters, slope_percent):
        """Calculate costs and ROI - REALISTIC for small properties"""
        
        # Municipal water cost: ~$1.50 per 1000 liters
        annual_savings = (harvest_liters / 1000) * 1.5
        
        # Storage system cost - MORE REALISTIC
        storage_liters = harvest_liters * 0.30
        
        # Realistic tank pricing for small/medium properties
        if storage_liters < 20000:
            tank_cost = 3000  # Single 10-20k tank
        elif storage_liters < 50000:
            tank_cost = storage_liters / 10000 * 2500  # $2500 per 10k liter
        else:
            tank_cost = storage_liters / 10000 * 2000  # Bulk discount
        
        # Collection system cost - REALISTIC
        if area_hectares < 2:
            collection_cost = 3000  # Small system
        elif area_hectares < 5:
            collection_cost = area_hectares * 2000
        else:
            collection_cost = area_hectares * 1500  # Economies of scale
        
        # Installation cost varies by slope
        if slope_percent < 10:
            installation_cost = 1500
        elif slope_percent < 20:
            installation_cost = 2500
        else:
            installation_cost = 4000
        
        total_cost = tank_cost + collection_cost + installation_cost
        
        payback_years = total_cost / annual_savings if annual_savings > 0 else 999
        
        return {
            'annual_water_savings_usd': round(annual_savings, 0),
            'system_costs': {
                'storage_tanks': round(tank_cost, 0),
                'collection_system': round(collection_cost, 0),
                'installation': round(installation_cost, 0),
                'total': round(total_cost, 0)
            },
            'roi': {
                'payback_years': round(payback_years, 1),
                'roi_percent': round((annual_savings / total_cost) * 100, 1) if total_cost > 0 else 0,
                'twenty_year_savings': round(annual_savings * 20 - total_cost, 0)
            }
        }
    
    def _save_water_harvesting_results(self, polygon_id, user_id, results):
        """Save results to database"""
        try:
            from services.database import DatabaseService
            db = DatabaseService()
            db.save_water_harvesting(polygon_id, user_id, results)
        except Exception as e:
            logger.error(f"Error saving to database: {e}")
            # Don't fail the whole request if database save fails