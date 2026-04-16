from django.contrib import admin
from .models import PlanTier, Policy


@admin.register(PlanTier)
class PlanTierAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'base_premium', 'weekly_coverage',
                     'is_recommended', 'is_active', 'sort_order')
    list_editable = ('sort_order', 'is_recommended', 'is_active')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display  = ('worker', 'plan_tier', 'status', 'weekly_premium',
                     'weekly_coverage', 'start_date', 'end_date', 'mandate_confirmed')
    list_filter   = ('status', 'plan_tier', 'mandate_confirmed')
    search_fields = ('worker__mobile', 'razorpay_subscription_id')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields  = ('worker', 'plan_tier')
    date_hierarchy = 'start_date'
