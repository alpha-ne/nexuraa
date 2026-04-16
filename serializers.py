"""apps/policies/serializers.py"""
from rest_framework import serializers
from .models import PlanTier, Policy


class PlanTierSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PlanTier
        fields = [
            'id', 'slug', 'name', 'description',
            'base_premium', 'weekly_coverage',
            'features', 'is_recommended', 'sort_order',
        ]


class PolicySerializer(serializers.ModelSerializer):
    plan_name       = serializers.CharField(source='plan_tier.name',            read_only=True)
    plan_slug       = serializers.CharField(source='plan_tier.slug',            read_only=True)
    coverage_display = serializers.CharField(read_only=True)
    premium_display  = serializers.CharField(read_only=True)
    days_remaining   = serializers.IntegerField(read_only=True)

    class Meta:
        model  = Policy
        fields = [
            'id', 'plan_name', 'plan_slug',
            'weekly_premium', 'weekly_coverage',
            'coverage_display', 'premium_display',
            'start_date', 'end_date', 'days_remaining',
            'status', 'mandate_confirmed',
            'created_at',
        ]
