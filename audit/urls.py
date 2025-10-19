from django.urls import path

from audit import views

urlpatterns = [
    path("", views.audit_dashboard, name="audit-dashboard"),
    path("pricing/", views.pricing, name="pricing"),
    path("checkout/<slug:slug>/", views.create_checkout_session, name="checkout"),
    path("audit/<int:pk>/download/", views.download_audit_pdf, name="audit-download"),
]
