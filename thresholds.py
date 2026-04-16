"""
apps/triggers/thresholds.py

Single source of truth for all disruption trigger thresholds.
Used by both the Celery polling tasks and the admin/UI.

Threshold table
---------------
Trigger          Full Payout       Partial (50%)
---------------- ----------------  ---------------
heavy_rain       > 35 mm/hr        20–35 mm/hr
extreme_heat     > 42 °C           38–42 °C
severe_aqi       > 300             200–300
flash_flood      official alert    —
curfew_strike    official order    —
platform_down    > 30 min outage   15–30 min
"""


class Thresholds:
    # ── Heavy Rain (OpenWeatherMap rain.1h, mm per hour) ──────────────────
    RAIN_FULL    = 35.0   # mm/hr → full payout
    RAIN_PARTIAL = 20.0   # mm/hr → 50 % payout

    # ── Extreme Heat (OpenWeatherMap temp, Celsius) ───────────────────────
    HEAT_FULL    = 42.0   # °C → full payout
    HEAT_PARTIAL = 38.0   # °C → 50 % payout

    # ── Severe AQI (WAQI index, 0–500+) ──────────────────────────────────
    AQI_FULL    = 300     # → full payout
    AQI_PARTIAL = 200     # → 50 % payout

    # ── Platform Downtime (minutes) ───────────────────────────────────────
    PLATFORM_FULL    = 30  # minutes → full payout
    PLATFORM_PARTIAL = 15  # minutes → 50 % payout


def evaluate_rain(mm_per_hour: float) -> tuple[bool, bool, float]:
    """
    Returns (is_trigger, is_full, severity_value).
    is_trigger: True if any threshold is breached.
    is_full:    True if full-payout threshold is breached.
    """
    if mm_per_hour >= Thresholds.RAIN_FULL:
        return True, True, mm_per_hour
    if mm_per_hour >= Thresholds.RAIN_PARTIAL:
        return True, False, mm_per_hour
    return False, False, mm_per_hour


def evaluate_heat(celsius: float) -> tuple[bool, bool, float]:
    if celsius >= Thresholds.HEAT_FULL:
        return True, True, celsius
    if celsius >= Thresholds.HEAT_PARTIAL:
        return True, False, celsius
    return False, False, celsius


def evaluate_aqi(aqi: float) -> tuple[bool, bool, float]:
    if aqi >= Thresholds.AQI_FULL:
        return True, True, aqi
    if aqi >= Thresholds.AQI_PARTIAL:
        return True, False, aqi
    return False, False, aqi


def evaluate_platform_downtime(minutes: float) -> tuple[bool, bool, float]:
    if minutes >= Thresholds.PLATFORM_FULL:
        return True, True, minutes
    if minutes >= Thresholds.PLATFORM_PARTIAL:
        return True, False, minutes
    return False, False, minutes
