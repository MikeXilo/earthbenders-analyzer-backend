"""
Water Harvesting Calculator Service
Calculates rainwater harvesting potential for a given polygon
"""
import requests
import logging
from typing import Dict, Any, Optional, Tuple
import math

logger = logging.getLogger(__name__)

class WaterHarvestingService:
    """Service for calculating water harvesting potential"""
    
    def __init__(self):
        self.worldclim_base_url = "https://biogeo.ucdavis.edu/data/worldclim/v2.1/base"
        
    def calculate_water_harvesting_potential(self, polygon_geometry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate water harvesting potential for a polygon
        
        Args:
            polygon_geometry: GeoJSON polygon
            
        Returns:
            Dict containing water harvesting analysis
        """
        try:
            # Step 1: Get polygon area and centroid
            area_hectares, centroid = self._calculate_polygon_area_and_centroid(polygon_geometry)
            
            # Step 2: Get rainfall data
            annual_rainfall = self._get_rainfall_data(centroid)
            
            # Step 3: Calculate runoff coefficient from slope (if available)
            # For now, use default values based on typical land use
            runoff_coefficient = self._estimate_runoff_coefficient()
            
            # Step 4: Calculate harvesting potential
            harvest_potential = self._calculate_harvest_potential(
                area_hectares, annual_rainfall, runoff_coefficient
            )
            
            # Step 5: Generate comparisons and insights
            comparisons = self._generate_comparisons(harvest_potential)
            
            return {
                'area_hectares': area_hectares,
                'area_square_meters': area_hectares * 10000,
                'annual_rainfall_mm': annual_rainfall,
                'runoff_coefficient': runoff_coefficient,
                'annual_harvest_liters': harvest_potential,
                'annual_harvest_gallons': harvest_potential * 0.264172,  # Convert to gallons
                'comparisons': comparisons,
                'recommendations': self._generate_recommendations(harvest_potential, area_hectares),
                'cost_analysis': self._calculate_cost_analysis(harvest_potential, area_hectares)
            }
            
        except Exception as e:
            logger.error(f"Error calculating water harvesting potential: {str(e)}")
            raise
    
    def _calculate_polygon_area_and_centroid(self, polygon_geometry: Dict[str, Any]) -> Tuple[float, Tuple[float, float]]:
        """Calculate polygon area in hectares and centroid coordinates"""
        try:
            # For now, use a simple approximation
            # In production, you'd use proper geospatial libraries
            coordinates = polygon_geometry['coordinates'][0]  # First ring of polygon
            
            # Simple area calculation (rough approximation)
            # This is a placeholder - in production use proper geospatial calculation
            area_sq_meters = 100000  # Placeholder - replace with actual calculation
            area_hectares = area_sq_meters / 10000
            
            # Calculate centroid
            lats = [coord[1] for coord in coordinates]
            lons = [coord[0] for coord in coordinates]
            centroid_lat = sum(lats) / len(lats)
            centroid_lon = sum(lons) / len(lons)
            
            return area_hectares, (centroid_lat, centroid_lon)
            
        except Exception as e:
            logger.error(f"Error calculating polygon area: {str(e)}")
            # Return default values
            return 1.0, (0.0, 0.0)
    
    def _get_rainfall_data(self, centroid: Tuple[float, float]) -> float:
        """Get annual rainfall data for the location"""
        try:
            lat, lon = centroid
            
            # For now, use a simple latitude-based estimation
            # In production, integrate with WorldClim API or similar
            if abs(lat) < 23.5:  # Tropical
                base_rainfall = 1500
            elif abs(lat) < 40:  # Subtropical
                base_rainfall = 800
            elif abs(lat) < 60:  # Temperate
                base_rainfall = 600
            else:  # Boreal
                base_rainfall = 400
            
            # Add some variation based on longitude (very rough)
            variation = (lon % 10) * 50  # Simple variation
            annual_rainfall = base_rainfall + variation
            
            logger.info(f"Estimated annual rainfall for {lat}, {lon}: {annual_rainfall}mm")
            return annual_rainfall
            
        except Exception as e:
            logger.error(f"Error getting rainfall data: {str(e)}")
            return 600  # Default fallback
    
    def _estimate_runoff_coefficient(self) -> float:
        """Estimate runoff coefficient based on typical land use"""
        # Typical runoff coefficients:
        # - Forest: 0.1-0.2
        # - Grassland: 0.2-0.4
        # - Agricultural: 0.3-0.5
        # - Urban: 0.7-0.9
        
        # For regenerative design, assume moderate coefficient
        return 0.7  # Conservative estimate for water harvesting potential
    
    def _calculate_harvest_potential(self, area_hectares: float, rainfall_mm: float, runoff_coefficient: float) -> float:
        """Calculate annual water harvesting potential in liters"""
        area_sq_meters = area_hectares * 10000
        annual_harvest_liters = area_sq_meters * rainfall_mm * runoff_coefficient
        return annual_harvest_liters
    
    def _generate_comparisons(self, harvest_liters: float) -> Dict[str, Any]:
        """Generate meaningful comparisons for the harvest potential"""
        olympic_pool_liters = 2500000  # 2.5 million liters
        swimming_pool_liters = 75000    # 75,000 liters (average home pool)
        household_daily = 300           # 300 liters per household per day
        
        return {
            'olympic_pools': harvest_liters / olympic_pool_liters,
            'swimming_pools': harvest_liters / swimming_pool_liters,
            'household_days': harvest_liters / household_daily,
            'household_years': (harvest_liters / household_daily) / 365,
            'irrigation_hectares': harvest_liters / 1000000,  # Rough estimate: 1M liters per hectare
        }
    
    def _generate_recommendations(self, harvest_liters: float, area_hectares: float) -> Dict[str, Any]:
        """Generate recommendations based on harvest potential"""
        recommendations = []
        
        if harvest_liters > 10000000:  # > 10M liters
            recommendations.append("Excellent water harvesting potential - consider large-scale storage systems")
            recommendations.append("Suitable for irrigation of multiple hectares")
        elif harvest_liters > 1000000:  # > 1M liters
            recommendations.append("Good water harvesting potential - consider medium-scale storage")
            recommendations.append("Suitable for irrigation and household use")
        else:
            recommendations.append("Moderate water harvesting potential - focus on key collection points")
            recommendations.append("Consider swales and small storage systems")
        
        # Add specific recommendations based on area
        if area_hectares > 5:
            recommendations.append("Large property - consider multiple collection zones")
        elif area_hectares > 1:
            recommendations.append("Medium property - focus on strategic collection points")
        else:
            recommendations.append("Small property - maximize roof and surface collection")
        
        return {
            'general': recommendations,
            'priority_actions': [
                "Install swales on contour to slow and spread water",
                "Create multiple small storage ponds rather than one large one",
                "Plant water-loving species in low-lying areas",
                "Consider gravity-fed irrigation systems"
            ]
        }
    
    def _calculate_cost_analysis(self, harvest_liters: float, area_hectares: float) -> Dict[str, Any]:
        """Calculate cost analysis for water harvesting systems"""
        # Rough cost estimates (these would be more sophisticated in production)
        storage_cost_per_liter = 0.5  # $0.50 per liter storage capacity
        system_cost_per_hectare = 2000  # $2000 per hectare for collection systems
        
        storage_cost = harvest_liters * storage_cost_per_liter
        collection_cost = area_hectares * system_cost_per_hectare
        total_cost = storage_cost + collection_cost
        
        # Calculate potential savings (vs municipal water)
        municipal_cost_per_liter = 0.001  # $1 per 1000 liters
        annual_savings = harvest_liters * municipal_cost_per_liter
        
        return {
            'storage_cost': storage_cost,
            'collection_cost': collection_cost,
            'total_cost': total_cost,
            'annual_savings': annual_savings,
            'payback_years': total_cost / annual_savings if annual_savings > 0 else float('inf'),
            'roi_percentage': (annual_savings / total_cost * 100) if total_cost > 0 else 0
        }
