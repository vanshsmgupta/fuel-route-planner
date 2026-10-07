from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from django.conf import settings
from scipy.spatial import cKDTree

from .geo import chord_to_miles, haversine, miles_to_chord, to_xyz
from .models import FuelStation


class FuelPlanError(Exception):
    status_code = 422


@dataclass
class Candidate:
    station_id: int
    price: float
    position: float  # miles from the start of the route
    offset: float  # miles off the route


@lru_cache(maxsize=1)
def station_table():
    rows = list(FuelStation.objects.values_list('id', 'lat', 'lng', 'price'))
    if not rows:
        raise FuelPlanError('No fuel stations loaded. Run "python manage.py load_data" first.')
    ids, lat, lng, price = zip(*rows)
    return np.array(ids), to_xyz(np.array(lat), np.array(lng)), np.array(price, dtype=float)


def densify(coords, step=0.5):
    """Add points so no gap along the line is longer than `step` miles."""
    pts = np.asarray(coords, dtype=float)
    lng, lat = pts[:, 0], pts[:, 1]
    seg = haversine(lat[:-1], lng[:-1], lat[1:], lng[1:])
    n = np.maximum(1, np.ceil(seg / step)).astype(int)
    idx = np.repeat(np.arange(len(seg)), n)
    t = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)) / np.repeat(n, n)
    cum = np.concatenate(([0], np.cumsum(seg)))

    d_lat = np.append(lat[idx] + (lat[idx + 1] - lat[idx]) * t, lat[-1])
    d_lng = np.append(lng[idx] + (lng[idx + 1] - lng[idx]) * t, lng[-1])
    d_cum = np.append(cum[idx] + seg[idx] * t, cum[-1])
    return d_lat, d_lng, d_cum


def stations_along_route(coords, total_miles, max_offset):
    ids, xyz, prices = station_table()
    lat, lng, cum = densify(coords)
    if cum[-1] > 0:
        cum = cum * (total_miles / cum[-1])  # line length vs OSRM's road distance

    tree = cKDTree(to_xyz(lat, lng))
    dist, nearest = tree.query(xyz, distance_upper_bound=miles_to_chord(max_offset))
    hits = np.flatnonzero(np.isfinite(dist))

    found = {}
    for i in hits:
        c = Candidate(int(ids[i]), float(prices[i]), float(cum[nearest[i]]), float(chord_to_miles(dist[i])))
        # stations are geocoded per city, so keep only the cheapest one at each spot
        spot = round(c.position, 1)
        if spot not in found or found[spot].price > c.price:
            found[spot] = c
    return sorted(found.values(), key=lambda c: (c.position, c.price))


def plan_stops(candidates, total_miles, tank_range, start_window, mpg, stop_penalty):
    """
    Cheapest way to buy fuel along the route, plus a fixed `stop_penalty` per stop so the
    plan doesn't detour for a gallon that saves a few cents.

    Dynamic programming over stations in route order. Fuel is tracked in whole miles of
    range (0..tank_range): cost[f] is the cheapest way to be at the current station with
    f miles left in the tank. The tank starts empty, so the trip begins at the cheapest
    station near the origin. Returns a list of (candidate, miles_of_fuel_bought).
    """
    if not candidates:
        raise FuelPlanError('No fuel stations found along this route.')

    near_start = [c for c in candidates if c.position <= min(start_window, total_miles)] or candidates[:1]
    first = min(near_start, key=lambda c: c.price)
    nodes = [first] + [c for c in candidates if first.position < c.position < total_miles]
    marks = np.rint([0] + [c.position for c in nodes[1:]] + [total_miles]).astype(int)
    gaps = np.diff(marks)
    if gaps.max() > tank_range:
        k = int(gaps.argmax())
        raise FuelPlanError(f'No fuel station within {tank_range} miles after mile {marks[k]} of the route.')

    levels = np.arange(tank_range + 1)
    cost = np.full(tank_range + 1, np.inf)
    cost[0] = 0.0
    sources = []
    for node, gap in zip(nodes, gaps):
        per_mile = node.price / mpg
        # filling from level g up to level f costs (f - g) * per_mile + stop_penalty
        h = cost - per_mile * levels
        best_h = np.minimum.accumulate(h)
        best_g = np.maximum.accumulate(np.where(h == best_h, levels, 0))
        prev_h = np.concatenate(([np.inf], best_h[:-1]))
        prev_g = np.concatenate(([0], best_g[:-1]))
        buy = prev_h + per_mile * levels + stop_penalty
        take = buy < cost
        after = np.where(take, buy, cost)
        sources.append(np.where(take, prev_g, levels))

        cost = np.full(tank_range + 1, np.inf)
        cost[:tank_range + 1 - gap] = after[gap:]

    # walk back from the destination to see what was bought where
    level = int(np.argmin(cost))
    stops = []
    for node, gap, source in zip(reversed(nodes), reversed(gaps), reversed(sources)):
        level += gap
        arrived = int(source[level])
        if arrived < level:
            stops.append((node, float(level - arrived)))
        level = arrived
    return stops[::-1]


def build_plan(route):
    total = route['distance_miles']
    mpg = settings.VEHICLE_MPG
    candidates = stations_along_route(route['coordinates'], total, settings.STATION_MAX_OFFSET_MILES)
    stops = plan_stops(
        candidates, total, settings.VEHICLE_RANGE_MILES, settings.START_SEARCH_MILES, mpg, settings.STOP_PENALTY,
    )

    stations = FuelStation.objects.in_bulk([c.station_id for c, _ in stops])
    result = []
    for c, miles in stops:
        s = stations[c.station_id]
        gallons = miles / mpg
        result.append({
            'opis_id': s.opis_id,
            'name': s.name,
            'address': s.address,
            'city': s.city,
            'state': s.state,
            'lat': s.lat,
            'lng': s.lng,
            'price_per_gallon': float(s.price),
            'miles_from_start': round(c.position, 1),
            'miles_off_route': round(c.offset, 1),
            'gallons': round(gallons, 2),
            'cost': round(gallons * float(s.price), 2),
        })
    return result
