"""
apps/zones/management/commands/verify_zones.py

Management command that checks zone fixture data is correctly loaded.

Usage:
    python manage.py verify_zones
"""
from django.core.management.base import BaseCommand
from apps.zones.models import Zone


class Command(BaseCommand):
    help = 'Verify that zone fixtures are loaded correctly'

    def handle(self, *args, **options):
        total = Zone.objects.count()
        if total == 0:
            self.stdout.write(self.style.ERROR(
                '✗ No zones found. Run: python manage.py loaddata zones'
            ))
            return

        self.stdout.write(self.style.SUCCESS(f'✓ {total} zones loaded\n'))

        cities = Zone.objects.values_list('city', flat=True).distinct().order_by('city')
        for city in cities:
            zones = Zone.objects.filter(city=city)
            active = zones.filter(active=True).count()
            avg_mult = sum(float(z.risk_multiplier) for z in zones) / zones.count()
            self.stdout.write(
                f'  {city:<12} — {active} active zones, '
                f'avg risk multiplier: {avg_mult:.2f}'
            )

        # Check risk distribution
        self.stdout.write('\nRisk level breakdown:')
        for level in ['Low', 'Moderate', 'High', 'Critical']:
            count = sum(1 for z in Zone.objects.filter(active=True) if z.risk_level == level)
            self.stdout.write(f'  {level:<10} {count} zones')

        self.stdout.write(self.style.SUCCESS('\n✓ Zone verification complete'))
