# Fuel Route Planner

Django API that takes a start and finish location in the USA, gets the driving route, and works out where to fuel up so the trip costs as little as possible. The vehicle has a 500 mile range and does 10 MPG. Fuel prices come from the provided CSV.

## Setup

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_data
python manage.py runserver
```

`load_data` loads the fuel price list and the US Census list of cities into SQLite. It takes a few seconds and doesn't need the internet (coordinates for the few cities missing from the Census file are already cached in `data/geocode_cache.json`).

## API

`GET /api/route/?start=<location>&finish=<location>`

or

`POST /api/route/` with `{"start": "...", "finish": "..."}`

A location can be `City, ST` (`Dallas, TX`, `St. Louis, Missouri`), `lat,lng` (`41.8781,-87.6298`) or a full address.

```bash
curl "http://127.0.0.1:8000/api/route/?start=Dallas,TX&finish=Denver,CO"
```

```json
{
  "start": {"query": "Dallas, TX", "name": "Dallas, TX", "lat": 32.793333, "lng": -96.766513},
  "finish": {"query": "Denver, CO", "name": "Denver, CO", "lat": 39.76185, "lng": -104.881105},
  "distance_miles": 779.4,
  "duration_hours": 14.5,
  "vehicle": {"range_miles": 500, "mpg": 10},
  "total_gallons": 77.9,
  "total_fuel_cost": 214.07,
  "fuel_stops": [
    {
      "opis_id": 66341,
      "name": "7-ELEVEN #218",
      "address": "I-44, EXIT 4",
      "city": "Harrold",
      "state": "TX",
      "lat": 34.06757,
      "lng": -99.033091,
      "price_per_gallon": 2.687,
      "miles_from_start": 176.2,
      "miles_off_route": 0.9,
      "gallons": 50.0,
      "cost": 134.35
    }
  ],
  "route": {"type": "LineString", "coordinates": [[-96.76651, 32.79333], "..."]},
  "map_url": "http://127.0.0.1:8000/api/route/map/?start=Dallas%2C+TX&finish=Denver%2C+CO"
}
```

`route` is GeoJSON, so it can go straight into Leaflet, Mapbox etc. `map_url` opens an HTML page with the route and the fuel stops drawn on a map.

Errors come back as `{"error": "..."}` with 400 (bad location), 422 (no route or no fuel station within range) or 502 (routing service down).

A Postman collection is in `postman_collection.json`.

## How it works

- **Geocoding**: `City, ST` is looked up in the local Census places table, so no external call is needed. Coordinates are used as they are. Only full addresses go to Nominatim.
- **Routing**: one call to the public OSRM server for the whole trip. The response is cached, so asking for the same trip again (or opening the map) doesn't call it again.
- **Stations on the route**: the station list has no coordinates, so each station is placed at its city from the Census data. The route line is split into points every half mile and a KD-tree finds which stations are within 5 miles of the route and how far along the route they are.
- **Choosing stops**: dynamic programming over the stations in route order, tracking how much fuel is left in the tank. It finds the cheapest way to buy fuel without ever going more than 500 miles between stops. Every stop also counts as an extra $5 so the plan doesn't stop for a gallon that saves a few cents.
- The vehicle starts with an empty tank and fills up at the cheapest station within 25 miles of the start.

A cross country request takes about 1-2 seconds, almost all of it waiting on OSRM. Repeated requests come back in under 50 ms.

The settings for range, MPG, the 5 mile limit, the stop cost and the OSRM/Nominatim URLs are at the bottom of `config/settings.py`.

## Tests

```bash
python manage.py test
```
