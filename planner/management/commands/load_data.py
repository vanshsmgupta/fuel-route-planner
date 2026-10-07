import csv
import io
import json
import re
import time
import zipfile
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from planner.fuel import station_table
from planner.geo import STATE_CODES, GeocodingError, nominatim_search, place_key
from planner.models import FuelStation, Place

DATA_DIR = settings.BASE_DIR / 'data'
SUFFIX_RE = re.compile(
    r'\s+(city and borough|consolidated government|unified government|metropolitan government|'
    r'metro government|urban county|municipality|borough|village|city|town|CDP|corporation)$',
    re.IGNORECASE,
)


class Command(BaseCommand):
    help = 'Load US places (for geocoding) and the fuel price list into the database.'

    def add_arguments(self, parser):
        parser.add_argument('--prices', default=str(DATA_DIR / 'fuel-prices-for-be-assessment.csv'))
        parser.add_argument('--places', default=str(DATA_DIR / '2024_Gaz_place_national.zip'))
        parser.add_argument('--offline', action='store_true', help='skip Nominatim for unknown cities')

    def handle(self, *args, **opts):
        places = self.read_places(opts['places'])
        stations, skipped = self.read_stations(opts['prices'], places, opts['offline'])

        with transaction.atomic():
            Place.objects.all().delete()
            FuelStation.objects.all().delete()
            Place.objects.bulk_create(
                [Place(key=k[1], state=k[0], name=v['name'], lat=v['lat'], lng=v['lng']) for k, v in places.items()],
                batch_size=2000,
            )
            FuelStation.objects.bulk_create(stations, batch_size=2000)
        station_table.cache_clear()

        self.stdout.write(self.style.SUCCESS(
            f'Loaded {len(places)} places and {len(stations)} fuel stations ({skipped} skipped).'
        ))

    def read_places(self, path):
        places = {}
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if n.endswith('.txt'))
            with zf.open(name) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'), delimiter='\t')
                for row in reader:
                    row = {k.strip(): v.strip() for k, v in row.items()}
                    if row['USPS'] not in STATE_CODES:
                        continue
                    city = SUFFIX_RE.sub('', row['NAME'].replace(' (balance)', ''))
                    item = {
                        'name': city,
                        'lat': float(row['INTPTLAT']),
                        'lng': float(row['INTPTLONG']),
                        'area': float(row['ALAND_SQMI']),
                    }
                    self.add_place(places, row['USPS'], place_key(city), item)
                    # "Nashville-Davidson" -> "Nashville", "Boise City" -> "Boise"
                    short = re.sub(r'\s+City$', '', re.split(r'[-/]', city)[0])
                    if short != city:
                        self.add_place(places, row['USPS'], place_key(short), dict(item, alias=True))
        return places

    def add_place(self, places, state, key, item):
        current = places.get((state, key))
        if current is not None:
            if item.get('alias') and not current.get('alias'):
                return
            if item.get('alias') == current.get('alias') and current['area'] >= item['area']:
                return
        places[(state, key)] = item

    def read_stations(self, path, places, offline):
        cache_file = DATA_DIR / 'geocode_cache.json'
        geocoded = json.loads(cache_file.read_text()) if cache_file.exists() else {}

        best = {}
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                state = row['State'].strip()
                if state not in STATE_CODES:
                    continue
                opis_id = int(row['OPIS Truckstop ID'])
                price = Decimal(row['Retail Price']).quantize(Decimal('0.001'))
                if opis_id in best and best[opis_id]['price'] <= price:
                    continue
                best[opis_id] = {
                    'opis_id': opis_id,
                    'name': row['Truckstop Name'].strip(),
                    'address': row['Address'].strip(),
                    'city': row['City'].strip(),
                    'state': state,
                    'rack_id': int(row['Rack ID']) if row['Rack ID'].strip() else None,
                    'price': price,
                }

        stations, skipped = [], 0
        for item in best.values():
            point = places.get((item['state'], place_key(item['city'])))
            if point is None:
                cache_key = f"{item['city']}|{item['state']}"
                if cache_key not in geocoded and not offline:
                    try:
                        geocoded[cache_key] = nominatim_search(f"{item['city']}, {item['state']}, USA")
                    except GeocodingError as exc:
                        self.stderr.write(str(exc))
                    time.sleep(1)  # nominatim usage policy
                point = geocoded.get(cache_key)
            if point is None:
                skipped += 1
                continue
            stations.append(FuelStation(lat=point['lat'], lng=point['lng'], **item))

        cache_file.write_text(json.dumps(geocoded, indent=1, sort_keys=True))
        return stations, skipped
