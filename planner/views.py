from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.views import APIView

from .fuel import FuelPlanError
from .geo import GeocodingError
from .routing import RoutingError
from .serializers import TripSerializer
from .services import plan_trip

TRIP_ERRORS = (GeocodingError, RoutingError, FuelPlanError)


class RoutePlanView(APIView):
    def get(self, request):
        return self.plan(request, request.query_params)

    def post(self, request):
        return self.plan(request, request.data)

    def plan(self, request, data):
        serializer = TripSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            trip = plan_trip(**serializer.validated_data)
        except TRIP_ERRORS as exc:
            return Response({'error': str(exc)}, status=exc.status_code)

        query = urlencode(serializer.validated_data)
        trip['map_url'] = request.build_absolute_uri(f"{reverse('route-map')}?{query}")
        return Response(trip)


def route_map(request):
    serializer = TripSerializer(data=request.GET)
    if not serializer.is_valid():
        return render(request, 'planner/map.html', {'error': 'Pass ?start=...&finish=... in the URL.'}, status=400)
    try:
        trip = plan_trip(**serializer.validated_data)
    except TRIP_ERRORS as exc:
        return render(request, 'planner/map.html', {'error': str(exc)}, status=exc.status_code)
    return render(request, 'planner/map.html', {'trip': trip})
