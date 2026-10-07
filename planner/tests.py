from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .fuel import Candidate, FuelPlanError, plan_stops, station_table
from .geo import GeocodingError, geocode, place_key
from .models import FuelStation, Place


def stations(*items):
    return [Candidate(i, price, pos, 0.0) for i, (pos, price) in enumerate(items)]


class PlanStopsTests(TestCase):
    def test_buys_cheap_fuel_and_carries_it(self):
        route = stations((0, 3.0), (300, 2.0), (600, 4.0))
        stops = plan_stops(route, 900, 500, 25, 10, 0)
        self.assertEqual([(c.position, miles) for c, miles in stops], [(0, 300), (300, 500), (600, 100)])

    def test_short_trip_needs_one_stop(self):
        stops = plan_stops(stations((2, 3.5), (80, 3.4)), 300, 500, 25, 10, 5)
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0][1], 300)

    def test_stop_penalty_skips_tiny_savings(self):
        route = stations((0, 3.00), (100, 2.99))
        self.assertEqual(len(plan_stops(route, 400, 500, 25, 10, 0)), 2)
        self.assertEqual(len(plan_stops(route, 400, 500, 25, 10, 5)), 1)

    def test_gap_longer_than_range(self):
        with self.assertRaises(FuelPlanError):
            plan_stops(stations((0, 3.0), (600, 3.0)), 900, 500, 25, 10, 0)

    def test_no_stations(self):
        with self.assertRaises(FuelPlanError):
            plan_stops([], 100, 500, 25, 10, 0)


class GeocodeTests(TestCase):
    def setUp(self):
        Place.objects.create(key=place_key('Saint Louis'), state='MO', name='St. Louis', lat=38.63, lng=-90.24)

    def test_coordinates(self):
        point = geocode('41.8781, -87.6298')
        self.assertEqual((point['lat'], point['lng']), (41.8781, -87.6298))

    def test_coordinates_outside_usa(self):
        with self.assertRaises(GeocodingError):
            geocode('48.8566, 2.3522')

    @mock.patch('planner.geo.requests.get')
    def test_city_state_uses_local_table(self, get):
        self.assertEqual(geocode('St. Louis, Missouri')['name'], 'St. Louis, MO')
        self.assertEqual(geocode('saint louis, mo')['name'], 'St. Louis, MO')
        get.assert_not_called()


class RouteApiTests(TestCase):
    def setUp(self):
        cache.clear()
        station_table.cache_clear()
        Place.objects.create(key='a', state='TX', name='A', lat=30.0, lng=-100.0)
        Place.objects.create(key='b', state='TX', name='B', lat=30.0, lng=-90.0)
        for n, (lng, price) in enumerate([(-99.99, '3.100'), (-95.0, '2.900'), (-92.0, '3.500')]):
            FuelStation.objects.create(
                opis_id=n, name=f'Stop {n}', address='I-10', city='X', state='TX',
                price=price, lat=30.0, lng=lng,
            )

    def tearDown(self):
        station_table.cache_clear()

    def osrm_response(self):
        resp = mock.Mock()
        resp.json.return_value = {
            'code': 'Ok',
            'routes': [{
                'distance': 600 * 1609.344,
                'duration': 9 * 3600,
                'geometry': {'type': 'LineString', 'coordinates': [[-100.0, 30.0], [-95.0, 30.0], [-90.0, 30.0]]},
            }],
        }
        return resp

    @mock.patch('planner.routing.requests.get')
    def test_route_plan(self, get):
        get.return_value = self.osrm_response()
        client = APIClient()

        resp = client.get('/api/route/', {'start': 'A, TX', 'finish': 'B, TX'})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data['distance_miles'], 600.0)
        self.assertEqual(data['total_gallons'], 60.0)
        self.assertEqual([s['name'] for s in data['fuel_stops']], ['Stop 0', 'Stop 1'])
        self.assertAlmostEqual(data['total_fuel_cost'], sum(s['cost'] for s in data['fuel_stops']), places=2)
        self.assertIn('/api/route/map/', data['map_url'])

        resp = client.post('/api/route/', {'start': 'A, TX', 'finish': 'B, TX'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get.call_count, 1)

        resp = client.get('/api/route/map/', {'start': 'A, TX', 'finish': 'B, TX'})
        self.assertContains(resp, 'Stop 1')
        self.assertEqual(get.call_count, 1)

    def test_missing_params(self):
        resp = APIClient().get('/api/route/', {'start': 'A, TX'})
        self.assertEqual(resp.status_code, 400)

    def test_location_outside_usa(self):
        resp = APIClient().get('/api/route/', {'start': '51.5, -0.12', 'finish': 'B, TX'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())
