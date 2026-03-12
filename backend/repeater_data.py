import math
import maidenhead
import httpx
import logging

logger = logging.getLogger(__name__)

# Cache for the dataset
_repeater_cache = None

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees)
    Returns distance in kilometers.
    """
    # convert decimal degrees to radians 
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])

    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371 # Radius of earth in kilometers
    return c * r

import xml.etree.ElementTree as ET
import re
import os

def load_local_data():
    """Loads the user's provided repeater KML list."""
    global _repeater_cache
    if _repeater_cache is not None:
        return _repeater_cache

    filepath = "/home/mjh/git/repeater-monitor/repeaters_2603041916.kml"
    repeaters = []
    
    try:
        if not os.path.exists(filepath):
            logger.warning(f"KML file not found at {filepath}, returning empty list.")
            return []
            
        tree = ET.parse(filepath)
        root = tree.getroot()
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
        
        for placemark in root.findall('.//kml:Placemark', ns):
            rep = {}
            
            name_elem = placemark.find('kml:name', ns)
            if name_elem is not None:
                rep['callsign'] = name_elem.text
                
            coords_elem = placemark.find('.//kml:coordinates', ns)
            if coords_elem is not None:
                parts = coords_elem.text.strip().split(',')
                if len(parts) >= 2:
                    rep['longitude'] = float(parts[0])
                    rep['latitude'] = float(parts[1])
                
            desc_elem = placemark.find('kml:description', ns)
            if desc_elem is not None and desc_elem.text:
                desc = desc_elem.text
                # Extract frequency from CDATA, ex: "<br>147.255000+ 162.2<br>"
                freq_match = re.search(r'<br>\s*([\d\.]+)[+-]?\s*.*<br>', desc)
                if freq_match:
                    rep['frequency'] = float(freq_match.group(1)) * 1e6 # Store as exact Hz internally
                    
            if 'latitude' in rep and 'longitude' in rep and 'frequency' in rep:
                repeaters.append(rep)
                
        _repeater_cache = repeaters
        logger.info(f"Loaded {len(_repeater_cache)} repeaters from local KML")
        return _repeater_cache
    except Exception as e:
        logger.error(f"Failed to parse KML data: {e}", exc_info=True)
        return []

def get_coordinates_from_input(location_input: str):
    """
    Returns (lat, lon) from a maidenhead grid square or a lat,lon string.
    """
    parts = location_input.replace(" ", "").split(",")
    if len(parts) == 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass
            
    # Assume grid square
    try:
        lat, lon = maidenhead.to_location(location_input.strip())
        return lat, lon
    except Exception as e:
        logger.error(f"Failed to parse location '{location_input}': {e}")
        return None, None

def get_repeaters_in_range(all_repeaters: list, lat: float, lon: float, radius_km: float = 100.0, band_segment: tuple = None):
    """
    Filter repeaters by distance and optionally by downilnk frequency band segment.
    band_segment is a tuple, e.g., (144.0, 148.0) MHz.
    """
    results = []
    for r in all_repeaters:
        try:
            r_lat = r["latitude"]
            r_lon = r["longitude"]
            
            # Distance check
            dist = haversine(lat, lon, r_lat, r_lon)
            if dist <= radius_km:
                # Frequency check
                freq_hz = r["frequency"]
                freq_mhz = freq_hz / 1e6
                
                # Standardize fields for the frontend
                r_copy = r.copy()
                r_copy["Downlink"] = f"{freq_mhz:.3f}"
                r_copy["Callsign"] = r.get("callsign", "RPT")
                r_copy["Lat"] = r_lat
                r_copy["Long"] = r_lon
                r_copy["distance_km"] = dist
                
                if band_segment:
                    low, high = band_segment
                    if not (low <= freq_mhz <= high):
                        continue
                        
                results.append(r_copy)
        except (ValueError, TypeError, KeyError) as e:
            logger.debug(f"Skipping repeater record due to error: {e}")
            pass

    # Sort by distance
    results.sort(key=lambda x: x["distance_km"])
    return results

