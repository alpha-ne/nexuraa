"""
management/commands/fire_trigger.py

Usage:
  python manage.py fire_trigger --zone 1 --type heavy_rain --severity 42.5
  python manage.py fire_trigger --zone 2 --type extreme_heat --severity 44.0 --partial
  python manage.py fire_trigger --zone 1 --type platform_down --severity 35 --platform swiggy
  python manage.py fire_trigger --all-zones --type severe_aqi --severity 320

This command is for development/demo only.
It creates a DisruptionEvent and immediately triggers the claim pipeline.
"""
from django.core.management.base import BaseCommand, CommandError
from apps.zones.models import Zone
from apps.triggers.models import DisruptionEvent
from apps.triggers.thresholds import Thresholds


class Command(BaseCommand):
    help = 'Manually fire a disruption trigger for testing'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--zone',      type=int,  help='Zone PK')
        group.add_argument('--all-zones', action='store_true', help='Fire for all active zones')

        parser.add_argument(
            '--type', required=True,
            choices=['heavy_rain', 'extreme_heat', 'severe_aqi',
                     'flash_flood', 'curfew_strike', 'platform_down'],
            help='Trigger type',
        )
        parser.add_argument('--severity', type=float, default=None,
                            help='Severity value (defaults to 10%% above threshold)')
        parser.add_argument('--partial', action='store_true',
                            help='Create partial trigger (50%% payout) instead of full')
        parser.add_argument('--platform', default='all',
                            choices=['zomato', 'swiggy', 'amazon', 'zepto', 'blinkit', 'dunzo', 'all'],
                            help='Platform (for platform_down trigger only)')
        parser.add_argument('--no-claims', action='store_true',
                            help='Skip triggering claim generation')

    def handle(self, *args, **options):
        trigger_type = options['type']
        is_full      = not options['partial']
        platform     = options['platform']

        # Default severity = 10% above threshold
        default_severity_map = {
            'heavy_rain':    Thresholds.RAIN_FULL    * 1.1,
            'extreme_heat':  Thresholds.HEAT_FULL    * 1.01,
            'severe_aqi':    Thresholds.AQI_FULL     * 1.1,
            'flash_flood':   1.0,
            'curfew_strike': 1.0,
            'platform_down': Thresholds.PLATFORM_FULL * 1.1,
        }
        threshold_map = {
            'heavy_rain':    Thresholds.RAIN_FULL,
            'extreme_heat':  Thresholds.HEAT_FULL,
            'severe_aqi':    float(Thresholds.AQI_FULL),
            'flash_flood':   1.0,
            'curfew_strike': 1.0,
            'platform_down': float(Thresholds.PLATFORM_FULL),
        }

        severity  = options['severity'] or default_severity_map[trigger_type]
        threshold = threshold_map[trigger_type]

        # Resolve zones
        if options['all_zones']:
            zones = list(Zone.objects.filter(active=True))
        else:
            try:
                zones = [Zone.objects.get(pk=options['zone'])]
            except Zone.DoesNotExist:
                raise CommandError(f"Zone {options['zone']} not found.")

        created = []
        for zone in zones:
            event = DisruptionEvent.objects.create(
                zone=zone,
                trigger_type=trigger_type,
                severity_value=severity,
                threshold_value=threshold,
                is_full_trigger=is_full,
                affected_platform=platform,
                source_api='management_command',
                raw_payload={'manual': True, 'severity': severity},
            )
            created.append(event)
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✓ Created {trigger_type} event #{event.pk} in {zone} '
                    f'(severity={severity:.1f}, full={is_full})'
                )
            )

        # Trigger claim generation
        if not options['no_claims'] and created:
            try:
                from apps.claims.tasks import process_pending_claims
                process_pending_claims.delay()
                self.stdout.write(self.style.SUCCESS(
                    f'\n✓ Claim generation task queued for {len(created)} event(s).'
                ))
            except Exception as e:
                self.stdout.write(self.style.WARNING(
                    f'\n⚠ Could not queue claim task: {e}'
                ))

        self.stdout.write(self.style.SUCCESS(
            f'\nTotal: {len(created)} DisruptionEvent(s) created.'
        ))
