"""
apps/pricing/tasks.py

recalculate_all_premiums
    Runs every Sunday at 8 PM IST via Celery Beat.
    For every worker with an active policy:
      1. Build 44-feature vector from live zone + forecast + claim history
      2. Run XGBoost pipeline → disruption_probability (risk_score)
      3. Calculate new weekly_premium using BASE×(1 + risk×(MAX_MULT-1))
      4. Update WorkerProfile.risk_score and Policy.weekly_premium
      5. Notify worker if premium changed by more than ±20%

recalculate_single_worker(worker_id)
    On-demand recalculation for a single worker (admin action / post-KYC).
"""
import logging
from celery import shared_task
from django.utils import timezone

from .loader import (
    load_models, models_available,
    predict_risk_score, calculate_premium,
)

logger = logging.getLogger(__name__)

NOTIFY_CHANGE_THRESHOLD = 0.20   # notify if premium changes by ±20%


# ── Main Sunday task ──────────────────────────────────────────────────────────

@shared_task(name='apps.pricing.tasks.recalculate_all_premiums')
def recalculate_all_premiums():
    """
    Sunday 8 PM — recalculate risk scores and premiums for all active workers.
    """
    from apps.policies.models import Policy

    # Ensure models are loaded
    if not models_available():
        load_models()

    active_policies = Policy.objects.filter(
        status='active',
    ).select_related(
        'worker', 'worker__workerprofile',
        'worker__workerprofile__zone',
        'plan_tier',
    )

    total     = active_policies.count()
    updated   = 0
    unchanged = 0
    errors    = 0

    logger.info("[pricing] Starting Sunday recalculation for %d active policies.", total)

    for policy in active_policies:
        try:
            result = _recalculate_one(policy)
            if result == 'updated':
                updated += 1
            else:
                unchanged += 1
        except Exception as exc:
            logger.error(
                "[pricing] Error recalculating policy %s (worker %s): %s",
                policy.pk, policy.worker.mobile, exc, exc_info=True,
            )
            errors += 1

    logger.info(
        "[pricing] Recalculation complete — %d updated, %d unchanged, %d errors.",
        updated, unchanged, errors,
    )
    return {'total': total, 'updated': updated, 'unchanged': unchanged, 'errors': errors}


def _recalculate_one(policy) -> str:
    """
    Recalculate risk and premium for one policy.
    Returns 'updated' or 'unchanged'.
    """
    worker  = policy.worker
    profile = worker.workerprofile
    plan    = policy.plan_tier

    # Get latest zone forecast
    forecast = None
    if profile.zone:
        try:
            forecast = profile.zone.forecasts.order_by('-generated_at').first()
        except Exception:
            pass

    # Run XGBoost inference
    new_risk_score = predict_risk_score(profile, forecast)
    new_premium    = calculate_premium(new_risk_score, float(plan.base_premium))

    old_risk_score = profile.risk_score
    old_premium    = float(policy.weekly_premium)

    # Update WorkerProfile.risk_score
    profile.risk_score      = new_risk_score
    profile.risk_updated_at = timezone.now()
    profile.save(update_fields=['risk_score', 'risk_updated_at'])

    # Update Policy.weekly_premium
    policy.weekly_premium = new_premium
    policy.save(update_fields=['weekly_premium', 'updated_at'])

    # Notify if change is significant
    if old_premium > 0:
        change_pct = abs(new_premium - old_premium) / old_premium
        if change_pct >= NOTIFY_CHANGE_THRESHOLD:
            _notify_premium_changed(worker, old_premium, new_premium, new_risk_score)
            logger.info(
                "[pricing] Worker %s: premium %s→%s (%.0f%% change, risk=%.4f)",
                worker.mobile, old_premium, new_premium,
                change_pct * 100, new_risk_score,
            )
            return 'updated'

    return 'unchanged'


# ── On-demand single worker ───────────────────────────────────────────────────

@shared_task(name='apps.pricing.tasks.recalculate_single_worker')
def recalculate_single_worker(worker_id: int):
    """
    Recalculate risk and premium for one specific worker.
    Called from admin actions or post-KYC verification.
    """
    from django.contrib.auth import get_user_model
    from apps.policies.models import Policy

    User = get_user_model()

    if not models_available():
        load_models()

    try:
        worker = User.objects.get(pk=worker_id, is_worker=True)
    except User.DoesNotExist:
        logger.error("[pricing] Worker %s not found.", worker_id)
        return

    try:
        policy = worker.policies.filter(status='active').latest('start_date')
    except Policy.DoesNotExist:
        logger.info("[pricing] Worker %s has no active policy — skipping.", worker.mobile)
        return

    result = _recalculate_one(policy)
    logger.info("[pricing] Single recalc for %s → %s", worker.mobile, result)
    return result


# ── Notification helper ───────────────────────────────────────────────────────

def _notify_premium_changed(worker, old_premium: float, new_premium: float, risk: float):
    """Queue a WhatsApp notification about premium change."""
    try:
        from apps.notifications.tasks import send_premium_update_notification
        send_premium_update_notification.delay(
            worker.pk,
            {'old': old_premium, 'new': new_premium, 'risk': risk},
        )
    except Exception as e:
        logger.warning("[pricing] Could not queue premium notification: %s", e)
