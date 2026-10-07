from django.db import models


class Place(models.Model):
    """US city/town from the Census gazetteer, used for offline geocoding."""

    key = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    name = models.CharField(max_length=120)
    lat = models.FloatField()
    lng = models.FloatField()

    class Meta:
        indexes = [models.Index(fields=['state', 'key'])]

    def __str__(self):
        return f'{self.name}, {self.state}'


class FuelStation(models.Model):
    opis_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    rack_id = models.IntegerField(null=True)
    price = models.DecimalField(max_digits=6, decimal_places=3)
    lat = models.FloatField()
    lng = models.FloatField()

    def __str__(self):
        return f'{self.name} ({self.city}, {self.state})'
