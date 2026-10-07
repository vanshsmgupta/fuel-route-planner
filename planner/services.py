import numpy as np
from django.conf import settings

from .fuel import build_plan
from .geo import geocode, haversine
from .routing import get_route


def thin_line(coords, step=1.0):
    """Keep roughly one point per `step` miles so the response stays small."""
    pts = np.asarray(coords)
    seg = haversine(pts[:-1, 1], pts[:-1, 0], pts[1:, 1], pts[1:, 0])
    marks = np.floor(np.concatenate(([0], np.cumsum(seg))) / step)
    keep = np.flatnonzero(np.diff(marks, prepend=-1) > 0)
    if keep[-1] != len(pts) - 1:
        keep = np.append(keep, len(pts) - 1)
    return [[round(x, 5), round(y, 5)] for x, y in pts[keep].tolist()]


def plan_trip(start, finish):
    start = geocode(start)
    finish = geocode(finish)
    route = get_route(start, finish)
    stops = build_plan(route)

    return {
        'start': start,
        'finish': finish,
        'distance_miles': round(route['distance_miles'], 1),
        'duration_hours': round(route['duration_hours'], 1),
        'vehicle': {'range_miles': settings.VEHICLE_RANGE_MILES, 'mpg': settings.VEHICLE_MPG},
        'total_gallons': round(sum(s['gallons'] for s in stops), 2),
        'total_fuel_cost': round(sum(s['cost'] for s in stops), 2),
        'fuel_stops': stops,
        'route': {'type': 'LineString', 'coordinates': thin_line(route['coordinates'])},
    }
