from django.urls import path

from audit import views

urlpatterns = [
    path("", views.audit_dashboard, name="audit-dashboard"),
]
