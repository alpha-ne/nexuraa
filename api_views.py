"""
apps/policies/api_views.py

GET  /api/v1/policies/plans/          → list all active plan tiers
GET  /api/v1/policies/my-policy/      → current worker policy
POST /api/v1/policies/select/<slug>/  → activate a plan (returns Razorpay URL or success)
POST /api/v1/policies/cancel/         → cancel active policy
"""
import logging
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from .models import PlanTier, Policy
from .serializers import PlanTierSerializer, PolicySerializer

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([AllowAny])
def list_plans(request):
    plans = PlanTier.objects.filter(is_active=True).order_by('sort_order')
    return Response(PlanTierSerializer(plans, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_policy_api(request):
    try:
        policy = request.user.policies.filter(status='active').latest('start_date')
        return Response(PolicySerializer(policy).data)
    except Policy.DoesNotExist:
        return Response({'detail': 'No active policy.'}, status=404)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def select_plan_api(request, slug):
    from .views import SelectPlanView, _create_razorpay_mandate, _hardcoded_plans
    from django.utils import timezone
    from datetime import timedelta
    from django.shortcuts import get_object_or_404

    try:
        plan = PlanTier.objects.get(slug=slug, is_active=True)
    except PlanTier.DoesNotExist:
        return Response({'error': 'Plan not found.'}, status=404)

    if not request.user.is_worker:
        return Response({'error': 'Workers only.'}, status=403)

    try:
        profile = request.user.workerprofile
    except Exception:
        return Response({'error': 'Profile not found.'}, status=404)

    # Cancel existing
    request.user.policies.filter(status__in=['active', 'pending']).update(status='cancelled')

    today      = timezone.now().date()
    days_ahead = (7 - today.weekday()) % 7 or 7
    start_date = today + timedelta(days=days_ahead)
    end_date   = start_date + timedelta(days=6)

    policy = Policy.objects.create(
        worker=request.user, plan_tier=plan,
        weekly_premium=plan.base_premium,
        weekly_coverage=plan.weekly_coverage,
        start_date=start_date, end_date=end_date,
        status='pending',
    )

    razorpay_url = _create_razorpay_mandate(request, policy, profile, plan)

    if razorpay_url:
        return Response({'razorpay_url': razorpay_url, 'policy_id': policy.pk})

    policy.status = 'active'
    policy.mandate_confirmed = True
    policy.save(update_fields=['status', 'mandate_confirmed'])

    return Response({
        'message': f'{plan.name} activated.',
        'policy':  PolicySerializer(policy).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_policy_api(request):
    try:
        policy = request.user.policies.filter(status='active').latest('start_date')
    except Policy.DoesNotExist:
        return Response({'error': 'No active policy.'}, status=404)

    policy.status = 'cancelled'
    policy.save(update_fields=['status'])
    return Response({'message': 'Policy cancelled.'})
