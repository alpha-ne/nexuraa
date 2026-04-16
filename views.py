"""
apps/policies/views.py

Web views:
  /plans/            → public plan listing (works for logged-out users too)
  /my-policy/        → worker's current policy detail (login required)
  /select-plan/<slug>/ → initiate plan purchase / Razorpay mandate
  /cancel-policy/    → cancel active policy
"""
import logging
from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.views import View
from django.utils.decorators import method_decorator

from .models import PlanTier, Policy

logger = logging.getLogger(__name__)

_login = login_required(login_url='accounts:login')


# ─── Public: Plan listing ─────────────────────────────────────────────────────

class PlansView(View):
    """
    Public page — lists all active plan tiers.
    If user is logged in and already has an active policy, highlights their
    current plan and shows an upgrade/downgrade CTA instead of purchase.
    """
    template_name = 'policies/plans.html'

    def get(self, request):
        plans = PlanTier.objects.filter(is_active=True).order_by('sort_order')

        # If no plans in DB yet (before fixtures are loaded), use hardcoded fallback
        if not plans.exists():
            plans = _hardcoded_plans()

        active_policy = None
        if request.user.is_authenticated and request.user.is_worker:
            try:
                active_policy = request.user.policies.filter(
                    status='active'
                ).latest('start_date')
            except Policy.DoesNotExist:
                pass

        # Pre-select plan from query string (?plan=standard)
        selected_slug = request.GET.get('plan', '')

        ctx = {
            'plans':         plans,
            'active_policy': active_policy,
            'selected_slug': selected_slug,
        }
        return render(request, self.template_name, ctx)


# ─── Authenticated: Select / purchase a plan ──────────────────────────────────

@method_decorator(_login, name='dispatch')
class SelectPlanView(View):
    """
    POST-only: worker selects a plan → creates Policy (pending) → Razorpay mandate flow.
    GET redirects to plans page.
    """
    template_name = 'policies/select_plan.html'

    def get(self, request, slug):
        plan = get_object_or_404(PlanTier, slug=slug, is_active=True)
        return render(request, self.template_name, {'plan': plan})

    def post(self, request, slug):
        if not request.user.is_worker:
            messages.error(request, 'Only workers can purchase a policy.')
            return redirect('core:home')

        try:
            profile = request.user.workerprofile
        except Exception:
            messages.error(request, 'Please complete your profile first.')
            return redirect('accounts:register_profile')

        if not profile.upi_id:
            messages.error(request, 'Please add your UPI ID before purchasing a plan.')
            return redirect('workers:account')

        plan = get_object_or_404(PlanTier, slug=slug, is_active=True)

        # Cancel any existing active policy
        existing = request.user.policies.filter(
            status__in=['active', 'pending']
        )
        if existing.filter(plan_tier=plan).exists():
            messages.info(request, f'You already have an active {plan.name}.')
            return redirect('policies:my_policy')

        existing.update(status='cancelled')

        # Calculate premium — base for now, XGBoost recalcs on Sunday
        weekly_premium = plan.base_premium

        today      = timezone.now().date()
        # Policy starts on next Monday
        days_ahead = (7 - today.weekday()) % 7 or 7
        start_date = today + timedelta(days=days_ahead)
        end_date   = start_date + timedelta(days=6)

        policy = Policy.objects.create(
            worker          = request.user,
            plan_tier       = plan,
            weekly_premium  = weekly_premium,
            weekly_coverage = plan.weekly_coverage,
            start_date      = start_date,
            end_date        = end_date,
            status          = 'pending',
        )

        # Attempt Razorpay Autopay mandate creation
        razorpay_url = _create_razorpay_mandate(request, policy, profile, plan)

        if razorpay_url:
            return redirect(razorpay_url)

        # Sandbox / test mode — activate immediately
        policy.status = 'active'
        policy.mandate_confirmed = True
        policy.save(update_fields=['status', 'mandate_confirmed'])

        messages.success(
            request,
            f'🎉 {plan.name} activated! You are now covered for ₹{int(plan.weekly_coverage):,}/week.'
        )
        return redirect('policies:my_policy')


def _create_razorpay_mandate(request, policy, profile, plan):
    """
    Create a Razorpay subscription (Autopay) for the given policy.
    Returns the Razorpay hosted payment URL, or None if in sandbox/test mode.
    """
    if not settings.RAZORPAY_KEY_ID or settings.RAZORPAY_KEY_ID.startswith('rzp_test_xxx'):
        logger.info(
            f"[Razorpay SANDBOX] Skipping real mandate for policy {policy.pk}"
        )
        return None

    try:
        import razorpay
        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )

        # Ensure Razorpay Contact exists for this worker
        if not profile.razorpay_contact_id:
            contact = client.contact.create({
                'name':    profile.name,
                'contact': f'+91{profile.user.mobile}',
                'type':    'customer',
            })
            profile.razorpay_contact_id = contact['id']
            profile.save(update_fields=['razorpay_contact_id'])

        # Create subscription
        subscription = client.subscription.create({
            'plan_id':        plan.razorpay_plan_id or settings.RAZORPAY_WEEKLY_PLAN_ID,
            'total_count':    52,      # 1 year of weekly payments
            'quantity':       1,
            'customer_notify': 1,
            'notes': {
                'policy_id':  str(policy.pk),
                'worker_id':  str(request.user.pk),
                'plan_slug':  plan.slug,
            },
        })

        policy.razorpay_subscription_id = subscription['id']
        policy.save(update_fields=['razorpay_subscription_id'])

        profile.razorpay_mandate_id = subscription['id']
        profile.save(update_fields=['razorpay_mandate_id'])

        return subscription.get('short_url')

    except Exception as e:
        logger.error(f"[Razorpay] Mandate creation failed for policy {policy.pk}: {e}")
        return None


# ─── Authenticated: My Policy ────────────────────────────────────────────────

@_login
def my_policy(request):
    """Worker's current policy detail page."""
    user = request.user

    active_policy = None
    past_policies = []
    try:
        active_policy = user.policies.filter(status='active').latest('start_date')
    except Policy.DoesNotExist:
        pass

    past_policies = user.policies.exclude(
        status='active'
    ).order_by('-start_date')[:6]

    ctx = {
        'active_policy': active_policy,
        'past_policies': past_policies,
        'plans':         PlanTier.objects.filter(is_active=True).order_by('sort_order'),
    }
    return render(request, 'policies/my_policy.html', ctx)


# ─── Authenticated: Cancel ────────────────────────────────────────────────────

@_login
def cancel_policy(request):
    """Cancel the worker's active policy."""
    if request.method != 'POST':
        return redirect('policies:my_policy')

    try:
        policy = request.user.policies.filter(status='active').latest('start_date')
    except Policy.DoesNotExist:
        messages.error(request, 'No active policy found.')
        return redirect('policies:my_policy')

    # Attempt Razorpay cancellation
    if policy.razorpay_subscription_id:
        try:
            import razorpay
            client = razorpay.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )
            client.subscription.cancel(policy.razorpay_subscription_id)
            logger.info(
                f"Razorpay subscription {policy.razorpay_subscription_id} cancelled."
            )
        except Exception as e:
            logger.warning(f"[Razorpay] Cancel failed: {e}")

    policy.status = 'cancelled'
    policy.save(update_fields=['status'])

    messages.success(
        request,
        'Your policy has been cancelled. You remain covered until the end of the current week.'
    )
    return redirect('policies:my_policy')


# ─── Hardcoded plan fallback ──────────────────────────────────────────────────

def _hardcoded_plans():
    """
    Used when the DB has no PlanTier rows yet (before fixtures are loaded).
    Returns a list of plain objects that the template can iterate over.
    """
    class FakePlan:
        def __init__(self, slug, name, base_premium, weekly_coverage,
                     features, is_recommended, sort_order):
            self.slug            = slug
            self.name            = name
            self.base_premium    = base_premium
            self.weekly_coverage = weekly_coverage
            self.features        = features
            self.is_recommended  = is_recommended
            self.sort_order      = sort_order
            self.razorpay_plan_id = ''

    return [
        FakePlan(
            slug='basic', name='Basic Shield',
            base_premium=29, weekly_coverage=500,
            features=[
                'All 6 trigger types',
                'Zero-touch auto-claim',
                'UPI payout < 2 hours',
                'WhatsApp alerts',
            ],
            is_recommended=False, sort_order=1,
        ),
        FakePlan(
            slug='standard', name='Standard Shield',
            base_premium=49, weekly_coverage=1000,
            features=[
                'All 6 trigger types',
                'Zero-touch auto-claim',
                'UPI payout < 2 hours',
                'WhatsApp alerts',
                'Weekly risk forecast',
                'Risk Circle access',
            ],
            is_recommended=True, sort_order=2,
        ),
        FakePlan(
            slug='premium', name='Premium Shield',
            base_premium=79, weekly_coverage=2000,
            features=[
                'All 6 trigger types',
                'Zero-touch auto-claim',
                'UPI payout < 2 hours',
                'WhatsApp + Email alerts',
                'Weekly risk forecast',
                'Risk Circle + IncomeDNA',
                'Priority support',
                'Dynamic risk pricing',
            ],
            is_recommended=False, sort_order=3,
        ),
    ]
