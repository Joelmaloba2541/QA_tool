from django.urls import include, path

from audit import views

urlpatterns = [
    path("", views.audit_dashboard, name="audit-dashboard"),
    path("pricing/", views.pricing, name="pricing"),
    path("checkout/<slug:slug>/", views.create_checkout_session, name="checkout"),
    path("audit/<int:pk>/download/", views.download_audit_pdf, name="audit-download"),
    path("accounts/login/", views.AuditLoginView.as_view(), name="login"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/", include("django.contrib.auth.urls")),
]
