"""
apps/zones/utils.py

Utility functions for zone-based geographic operations.
Used by:
  - apps.fraud  → GPS zone validation (Layer 3 of fraud pipeline)
  - apps.triggers → zone-aware disruption event creation
"""
import math
from typing import Optional
from .models import Zone


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate the great-circle distance between two GPS coordinates in kilometres.
    Uses the Haversine formula.
    """
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlam  = math.radians(lng2 - lng1)

    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_within_zone(zone: Zone, lat: float, lng: float) -> bool:
    """
    Return True if the given GPS coordinates are within the zone's circular boundary.
    Uses the zone's centre point (lat/lng) and radius_km.
    """
    dist = haversine_km(
        float(zone.lat), float(zone.lng),
        lat, lng
    )
    return dist <= float(zone.radius_km)


def find_zone_for_coords(lat: float, lng: float,
                          city: Optional[str] = None) -> Optional[Zone]:
    """
    Find the first active Zone whose boundary contains the given coordinates.
    Optionally filter by city to speed up the lookup.

    Returns the matching Zone instance, or None if no zone matches.
    """
    qs = Zone.objects.filter(active=True)
    if city:
        qs = qs.filter(city=city)

    for zone in qs:
        if is_within_zone(zone, lat, lng):
            return zone
    return None


def get_zones_for_city(city: str) -> list:
    """Return all active zones for a given city, ordered by area name."""
    return list(Zone.objects.filter(city=city, active=True).order_by('area_name'))


def get_all_active_zones() -> list:
    """Return all active zones — used by Celery trigger polling tasks."""
    return list(Zone.objects.filter(active=True).select_related())
