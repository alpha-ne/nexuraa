"""
apps/pricing/loader.py

XGBoost Risk Pricing Model — loader and feature engineering.

Trained model files (loaded once per worker process):
  risk_model.pkl          — sklearn Pipeline (XGBClassifier + IsotonicCalibration)
  risk_model_xgb.json     — raw XGBClassifier weights (backup)
  feature_list.json       — 44 feature names in exact training order
  model_metadata.json     — pricing constants: base_premium=150, max_multiplier=3.0

Model output: disruption probability (0.0–1.0)
Premium formula: base_premium × (1 + risk_score × (max_multiplier - 1))
  e.g. risk=0.0 → ₹150 × 1.0 = ₹150   (minimum)
       risk=0.5 → ₹150 × 2.0 = ₹300
       risk=1.0 → ₹150 × 3.0 = ₹450   (maximum)

The plan premium is then clamped to [plan.base_premium × 0.8, plan.base_premium × 1.5].

44 Features (exact training order):
  tenure_months, average_daily_earnings, active_hours_per_day,
  historical_rain_events, historical_heat_events, average_aqi,
  flood_frequency, curfew_incidents, month, is_monsoon_week,
  forecasted_rain_mm, forecasted_max_temp_c, forecasted_aqi,
  flood_alert_level, curfew_flag, past_claim_count,
  claim_frequency_last_6m, last_claim_days_ago, total_payout_last_year,
  zone_risk_encoded, weather_stress_index, earnings_vulnerability,
  experience_risk_factor, zone_hazard_score, claim_recency_weight,
  extreme_heat_flag, severe_aqi_flag, heavy_rain_flag,
  delivery_segment_ecommerce, delivery_segment_food, delivery_segment_grocery,
  season_monsoon, season_spring, season_summer, season_winter,
  city_tier_tier1, city_tier_tier2, city_tier_tier3,
  vehicle_type_bicycle, vehicle_type_car, vehicle_type_motorcycle,
  weekday_pattern_mixed, weekday_pattern_weekday_heavy,
  weekday_pattern_weekend_heavy
"""
import json
import logging
import math
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Module-level model cache ──────────────────────────────────────────────────
_pipeline       = None   # sklearn Pipeline (preferred)
_xgb_model      = None   # raw XGBClassifier (backup)
_feature_list   = None   # list[str], 44 names
_metadata       = None   # dict from model_metadata.json
_models_loaded  = False

BASE_PREMIUM_INR  = 150.0   # fallback if metadata missing
MAX_MULTIPLIER    = 3.0


def load_models() -> bool:
    """
    Lazy-load all pricing models from ML_MODELS_DIR.
    Safe to call multiple times — idempotent.
    Returns True on success.
    """
    global _pipeline, _xgb_model, _feature_list, _metadata, _models_loaded
    global BASE_PREMIUM_INR, MAX_MULTIPLIER

    if _models_loaded:
        return True

    models_dir = settings.ML_MODELS_DIR

    try:
        import joblib

        # ── sklearn Pipeline (XGBoost + Isotonic Calibration) ────────────
        pkl_path = models_dir / 'risk_model.pkl'
        if pkl_path.exists():
            _pipeline = joblib.load(pkl_path)
            logger.info("[pricing] risk_model.pkl loaded (pipeline: %s)", type(_pipeline))

        # ── Raw XGBoost (backup) ──────────────────────────────────────────
        xgb_path = models_dir / 'risk_model_xgb.json'
        if xgb_path.exists():
            import xgboost as xgb
            _xgb_model = xgb.XGBClassifier()
            _xgb_model.load_model(str(xgb_path))
            logger.info("[pricing] risk_model_xgb.json loaded")

        # ── Feature list ─────────────────────────────────────────────────
        feat_path = models_dir / 'feature_list.json'
        if feat_path.exists():
            with open(feat_path) as f:
                _feature_list = json.load(f)
            logger.info("[pricing] feature_list.json loaded (%d features)", len(_feature_list))

        # ── Metadata ─────────────────────────────────────────────────────
        meta_path = models_dir / 'model_metadata.json'
        if meta_path.exists():
            with open(meta_path) as f:
                _metadata = json.load(f)
            pricing         = _metadata.get('pricing', {})
            BASE_PREMIUM_INR = float(pricing.get('base_premium_inr', 150))
            MAX_MULTIPLIER   = float(pricing.get('max_multiplier', 3.0))
            logger.info(
                "[pricing] Metadata loaded — base=₹%s max_mult=%.1f",
                BASE_PREMIUM_INR, MAX_MULTIPLIER,
            )

        _models_loaded = (_pipeline is not None or _xgb_model is not None)
        return _models_loaded

    except ImportError as e:
        logger.error("[pricing] Required ML library missing: %s", e)
        return False
    except Exception as e:
        logger.error("[pricing] Model loading error: %s", e, exc_info=True)
        return False


def models_available() -> bool:
    return _models_loaded and (_pipeline is not None or _xgb_model is not None)


# ── Feature engineering ───────────────────────────────────────────────────────

def build_feature_vector(worker_profile, forecast=None) -> dict:
    """
    Build the 44-feature dict for XGBoost risk scoring.

    Parameters
    ----------
    worker_profile : WorkerProfile instance
    forecast       : ZoneForecast instance (optional — uses zone's latest if None)

    Returns a flat dict with all 44 keys in exact training order.
    """
    from django.utils import timezone
    from datetime import timedelta
    from apps.claims.models import Claim

    profile = worker_profile
    user    = profile.user
    zone    = profile.zone
    now     = timezone.now()
    today   = now.date()

    # ── Tenure ────────────────────────────────────────────────────────────
    tenure_days   = (today - user.date_joined.date()).days
    tenure_months = max(tenure_days / 30.0, 0)

    # ── Historical earnings proxy ─────────────────────────────────────────
    # We don't track earnings directly; use payout history as proxy
    total_payout_yr = float(sum(
        p.amount for p in user.payouts.filter(
            status='credited',
            credited_at__gte=now - timedelta(days=365),
        )
    ))
    # Rough daily earnings estimate: assume ₹600/day for 8h active
    avg_daily_earnings = 600.0
    active_hours       = 8.0

    # ── Claim history ─────────────────────────────────────────────────────
    all_claims    = Claim.objects.filter(worker=user)
    claim_count   = all_claims.count()
    claims_6m     = all_claims.filter(
        created_at__gte=now - timedelta(days=180)
    ).count()

    last_claim = all_claims.order_by('-created_at').first()
    last_claim_days = (
        (today - last_claim.created_at.date()).days
        if last_claim else 999
    )

    # ── Zone historical risk ───────────────────────────────────────────────
    from apps.triggers.models import DisruptionEvent

    zone_events_yr = 0
    rain_events    = 0
    heat_events    = 0
    flood_freq     = 0
    curfew_count   = 0
    avg_aqi        = 100.0

    if zone:
        zone_qs = DisruptionEvent.objects.filter(
            zone=zone,
            started_at__gte=now - timedelta(days=365),
        )
        zone_events_yr = zone_qs.count()
        rain_events    = zone_qs.filter(trigger_type='heavy_rain').count()
        heat_events    = zone_qs.filter(trigger_type='extreme_heat').count()
        flood_freq     = zone_qs.filter(trigger_type='flash_flood').count()
        curfew_count   = zone_qs.filter(trigger_type='curfew_strike').count()

    # ── Zone risk encoding ────────────────────────────────────────────────
    zone_risk_enc = float(zone.risk_multiplier) if zone else 1.0

    # ── Calendar features ─────────────────────────────────────────────────
    month        = today.month
    is_monsoon   = int(month in (6, 7, 8, 9))
    season_mon   = int(month in (6, 7, 8, 9))
    season_spr   = int(month in (3, 4, 5))
    season_sum   = int(month in (4, 5, 6))
    season_win   = int(month in (11, 12, 1, 2))

    # ── Forecast features ─────────────────────────────────────────────────
    rain_mm   = 0.0
    max_temp  = 32.0
    aqi_fcst  = 100.0
    flood_alrt = 0
    curfew_f  = 0

    if forecast is None and zone:
        try:
            forecast = zone.forecasts.order_by('-generated_at').first()
        except Exception:
            pass

    if forecast:
        rain_mm   = float(forecast.rain_probability) * 50     # probability → mm proxy
        aqi_fcst  = float(forecast.aqi_probability)  * 300
        max_temp  = 38.0 if float(forecast.heat_probability) > 0.5 else 30.0

    # ── Derived risk scores ───────────────────────────────────────────────
    weather_stress = round(
        0.4 * min(rain_mm / 35.0, 1.0) +
        0.3 * min(max(max_temp - 35.0, 0) / 7.0, 1.0) +
        0.3 * min(aqi_fcst / 300.0, 1.0),
        4,
    )
    earnings_vuln    = round(min(total_payout_yr / 50000.0, 1.0), 4)
    experience_risk  = round(max(1.0 - tenure_months / 24.0, 0.0), 4)
    zone_hazard      = round(min(zone_events_yr / 20.0, 1.0), 4)
    claim_recency_wt = round(1.0 / max(last_claim_days / 30.0, 1.0), 4)

    # Threshold flags
    extreme_heat_f  = int(max_temp > 42)
    severe_aqi_f    = int(aqi_fcst > 300)
    heavy_rain_f    = int(rain_mm > 35)

    # ── Platform one-hot ──────────────────────────────────────────────────
    platform      = profile.platform or 'other'
    seg_food      = int(platform in ('zomato', 'swiggy'))
    seg_ecomm     = int(platform in ('amazon',))
    seg_groc      = int(platform in ('zepto', 'blinkit', 'dunzo'))

    # ── City tier ─────────────────────────────────────────────────────────
    tier1_cities = {'Mumbai', 'Delhi', 'Bangalore', 'Chennai', 'Hyderabad', 'Kolkata'}
    tier2_cities = {'Pune'}
    city = zone.city if zone else ''
    city_t1 = int(city in tier1_cities)
    city_t2 = int(city in tier2_cities)
    city_t3 = int(city not in tier1_cities and city not in tier2_cities)

    # ── Vehicle type ──────────────────────────────────────────────────────
    segment = profile.segment or 'bike'
    v_bike = int(segment == 'bike')
    v_bicy = int(segment == 'bicycle')
    v_car  = int(segment == 'car')

    # ── Weekday pattern (proxy — assume mixed) ────────────────────────────
    wp_mixed    = 1
    wp_weekday  = 0
    wp_weekend  = 0

    return {
        'tenure_months':              round(tenure_months, 2),
        'average_daily_earnings':     avg_daily_earnings,
        'active_hours_per_day':       active_hours,
        'historical_rain_events':     rain_events,
        'historical_heat_events':     heat_events,
        'average_aqi':                avg_aqi,
        'flood_frequency':            flood_freq,
        'curfew_incidents':           curfew_count,
        'month':                      month,
        'is_monsoon_week':            is_monsoon,
        'forecasted_rain_mm':         round(rain_mm, 2),
        'forecasted_max_temp_c':      round(max_temp, 2),
        'forecasted_aqi':             round(aqi_fcst, 2),
        'flood_alert_level':          flood_alrt,
        'curfew_flag':                curfew_f,
        'past_claim_count':           claim_count,
        'claim_frequency_last_6m':    claims_6m,
        'last_claim_days_ago':        last_claim_days,
        'total_payout_last_year':     round(total_payout_yr, 2),
        'zone_risk_encoded':          zone_risk_enc,
        'weather_stress_index':       weather_stress,
        'earnings_vulnerability':     earnings_vuln,
        'experience_risk_factor':     experience_risk,
        'zone_hazard_score':          zone_hazard,
        'claim_recency_weight':       claim_recency_wt,
        'extreme_heat_flag':          extreme_heat_f,
        'severe_aqi_flag':            severe_aqi_f,
        'heavy_rain_flag':            heavy_rain_f,
        'delivery_segment_ecommerce': seg_ecomm,
        'delivery_segment_food':      seg_food,
        'delivery_segment_grocery':   seg_groc,
        'season_monsoon':             season_mon,
        'season_spring':              season_spr,
        'season_summer':              season_sum,
        'season_winter':              season_win,
        'city_tier_tier1':            city_t1,
        'city_tier_tier2':            city_t2,
        'city_tier_tier3':            city_t3,
        'vehicle_type_bicycle':       v_bicy,
        'vehicle_type_car':           v_car,
        'vehicle_type_motorcycle':    v_bike,
        'weekday_pattern_mixed':      wp_mixed,
        'weekday_pattern_weekday_heavy': wp_weekday,
        'weekday_pattern_weekend_heavy': wp_weekend,
    }


def predict_risk_score(worker_profile, forecast=None) -> float:
    """
    Run the XGBoost pipeline on a WorkerProfile.
    Returns disruption_probability in [0.0, 1.0].
    Falls back to zone.risk_multiplier / 3.0 if models unavailable.
    """
    if not models_available():
        load_models()

    features = build_feature_vector(worker_profile, forecast)

    if not models_available():
        # Fallback: zone risk multiplier scaled to 0–1
        zone = worker_profile.zone
        return min(float(zone.risk_multiplier) / MAX_MULTIPLIER, 1.0) if zone else 0.5

    try:
        import pandas as pd

        df = pd.DataFrame([features])
        if _feature_list:
            for col in _feature_list:
                if col not in df.columns:
                    df[col] = 0
            df = df[_feature_list]

        # Prefer calibrated pipeline
        if _pipeline is not None:
            prob = float(_pipeline.predict_proba(df)[0][1])
        else:
            prob = float(_xgb_model.predict_proba(df)[0][1])

        return round(max(0.0, min(1.0, prob)), 4)

    except Exception as e:
        logger.error("[pricing] predict_risk_score failed: %s", e, exc_info=True)
        zone = worker_profile.zone
        return min(float(zone.risk_multiplier) / MAX_MULTIPLIER, 1.0) if zone else 0.5


def calculate_premium(risk_score: float, plan_base_premium: float) -> float:
    """
    Convert a risk_score → weekly premium (₹).

    Formula:
        raw = BASE_PREMIUM_INR × (1 + risk_score × (MAX_MULTIPLIER - 1))
        Clamped to [plan_base × 0.80, plan_base × 1.50]

    Examples (BASE=150, MAX_MULT=3.0):
        risk=0.0 → ₹150  (minimum)
        risk=0.5 → ₹300
        risk=1.0 → ₹450  (maximum before clamp)

    The clamp ensures the plan price stays within ±50% of the advertised rate.
    """
    raw = BASE_PREMIUM_INR * (1.0 + risk_score * (MAX_MULTIPLIER - 1.0))
    min_p = plan_base_premium * 0.80
    max_p = plan_base_premium * 1.50
    return round(max(min_p, min(max_p, raw)), 2)
