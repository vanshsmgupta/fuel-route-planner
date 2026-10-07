from django.contrib import admin

from .models import FuelStation, Place


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ('opis_id', 'name', 'city', 'state', 'price')
    list_filter = ('state',)
    search_fields = ('name', 'city')


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'state', 'lat', 'lng')
    list_filter = ('state',)
    search_fields = ('name',)
