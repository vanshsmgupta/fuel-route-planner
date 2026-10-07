import hashlib
import re

import numpy as np
import requests
from django.conf import settings
from django.core.cache import cache

EARTH_RADIUS_MILES = 3958.8

STATES = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA',
    'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE', 'district of columbia': 'DC',
    'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL',
    'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA',
    'maine': 'ME', 'maryland': 'MD', 'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN',
    'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
    'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY',
    'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR',
    'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD',
    'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT', 'vermont': 'VT', 'virginia': 'VA',
    'washington': 'WA', 'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY',
}
STATE_CODES = set(STATES.values())

COORDS_RE = re.compile(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$')


class GeocodingError(Exception):
    status_code = 400


def place_key(name):
    s = name.strip().lower().replace('.', '').replace("'", '')
    s = re.sub(r'\bst\b', 'saint', s)
    s = re.sub(r'\bste\b', 'sainte', s)
    s = re.sub(r'\bft\b', 'fort', s)
    s = re.sub(r'\bmt\b', 'mount', s)
    return re.sub(r'[\s\-]+', '', s)


def state_code(value):
    value = value.strip()
    if value.upper() in STATE_CODES:
        return value.upper()
    return STATES.get(value.lower())


def in_usa(lat, lng):
    return (
        (24.3 <= lat <= 49.5 and -125.0 <= lng <= -66.8)  # lower 48
        or (51.0 <= lat <= 71.6 and -180.0 <= lng <= -129.9)  # alaska
        or (18.8 <= lat <= 22.4 and -160.5 <= lng <= -154.7)  # hawaii
    )


def nominatim_search(query):
    key = 'nominatim:' + hashlib.md5(query.lower().encode()).hexdigest()
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        resp = requests.get(
            f'{settings.NOMINATIM_URL}/search',
            params={'q': query, 'format': 'json', 'limit': 1, 'countrycodes': 'us'},
            headers={'User-Agent': settings.HTTP_USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
    except requests.RequestException as exc:
        raise GeocodingError(f'Geocoding service failed: {exc}')
    result = None
    if results:
        r = results[0]
        result = {'name': r['display_name'], 'lat': float(r['lat']), 'lng': float(r['lon'])}
    cache.set(key, result)
    return result


def geocode(query):
    """Turn "lat,lng", "City, ST" or a free form US address into a point."""
    from .models import Place

    query = (query or '').strip()
    if not query:
        raise GeocodingError('Location is empty.')

    m = COORDS_RE.match(query)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if not in_usa(lat, lng):
            raise GeocodingError(f'"{query}" is not inside the USA.')
        return {'query': query, 'name': query, 'lat': lat, 'lng': lng}

    parts = [p.strip() for p in query.split(',')]
    parts = [p for p in parts if p and p.lower() not in ('usa', 'us', 'united states')]
    if len(parts) == 2 and state_code(parts[1]):
        place = Place.objects.filter(state=state_code(parts[1]), key=place_key(parts[0])).first()
        if place:
            return {'query': query, 'name': str(place), 'lat': place.lat, 'lng': place.lng}

    found = nominatim_search(query)
    if not found or not in_usa(found['lat'], found['lng']):
        raise GeocodingError(f'Could not find "{query}" in the USA.')
    return {'query': query, **found}


def haversine(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def to_xyz(lat, lng):
    lat, lng = np.radians(lat), np.radians(lng)
    return np.column_stack((np.cos(lat) * np.cos(lng), np.cos(lat) * np.sin(lng), np.sin(lat)))


def miles_to_chord(miles):
    return 2 * np.sin(miles / (2 * EARTH_RADIUS_MILES))


def chord_to_miles(chord):
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.minimum(chord, 2) / 2)
