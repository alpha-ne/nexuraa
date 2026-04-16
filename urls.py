# apps/policies/urls.py
from django.urls import path
from . import views

app_name = 'policies'

urlpatterns = [
    path('plans/',                   views.PlansView.as_view(),     name='plans'),
    path('plans/<slug:slug>/',       views.SelectPlanView.as_view(), name='select_plan'),
    path('my-policy/',               views.my_policy,               name='my_policy'),
    path('my-policy/cancel/',        views.cancel_policy,           name='cancel_policy'),
]
