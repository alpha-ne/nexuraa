# apps/policies/api_urls.py
from django.urls import path
from . import api_views

urlpatterns = [
    path('plans/',              api_views.list_plans,       name='api_list_plans'),
    path('my-policy/',          api_views.my_policy_api,    name='api_my_policy'),
    path('select/<slug:slug>/', api_views.select_plan_api,  name='api_select_plan'),
    path('cancel/',             api_views.cancel_policy_api, name='api_cancel_policy'),
]
