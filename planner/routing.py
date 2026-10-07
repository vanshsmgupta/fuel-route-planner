import requests
from django.conf import settings
from django.core.cache import cache

METERS_PER_MILE = 1609.344


class RoutingError(Exception):
    status_code = 502


class NoRouteFound(RoutingError):
    status_code = 422


def get_route(start, finish):
    """Single OSRM call for the whole trip. Results are cached so repeat lookups are free."""
    coords = f"{start['lng']:.5f},{start['lat']:.5f};{finish['lng']:.5f},{finish['lat']:.5f}"
    key = f'route:{coords}'
    route = cache.get(key)
    if route is not None:
        return route

    try:
        resp = requests.get(
            f'{settings.OSRM_URL}/route/v1/driving/{coords}',
            params={'overview': 'full', 'geometries': 'geojson'},
            headers={'User-Agent': settings.HTTP_USER_AGENT},
            timeout=20,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise RoutingError(f'Routing service failed: {exc}')

    if data.get('code') != 'Ok' or not data.get('routes'):
        raise NoRouteFound(data.get('message') or 'No driving route found between these locations.')

    best = data['routes'][0]
    route = {
        'distance_miles': best['distance'] / METERS_PER_MILE,
        'duration_hours': best['duration'] / 3600,
        'coordinates': best['geometry']['coordinates'],  # [lng, lat]
    }
    cache.set(key, route)
    return route
