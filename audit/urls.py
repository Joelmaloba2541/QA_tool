from django.urls import include, path
from django.views.generic import RedirectView
from django.templatetags.static import static

from audit import views

urlpatterns = [
    path("", views.audit_dashboard, name="audit-dashboard"),
    path("pricing/", views.pricing, name="pricing"),
    path("pricing/checkout/<slug:slug>/", views.payment_checkout, name="payment-checkout"),
    path("pricing/gateway/callback/", views.payment_gateway_callback, name="payment-gateway-callback"),
    path("pricing/gateway/<slug:slug>/", views.payment_gateway_redirect, name="payment-gateway"),
    path("checkout/<slug:slug>/", views.create_checkout_session, name="checkout"),
    path("audit/<int:pk>/download/", views.download_audit_pdf, name="audit-download"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("favicon.ico", RedirectView.as_view(url=static("audit/favicon.svg"), permanent=True)),
    path("accounts/login/", views.AuditLoginView.as_view(), name="login"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/", include("django.contrib.auth.urls")),
]
