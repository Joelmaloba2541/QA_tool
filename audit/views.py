import uuid

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, path, include

from audit.models import AuditRun, Payment, SubscriptionPlan, UserSubscription, Website
from audit.services import generate_audit_pdf, run_audit

urlpatterns = [
    path('robots.txt', robots_txt),
]

class AuditLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return self.get_redirect_url() or reverse_lazy("audit-dashboard")


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow:",
    ]
    content = "\n".join(lines) + "\n"
    return HttpResponse(content, content_type="text/plain")


def _resolve_subscription(user):
    if not user:
        return None
    subscription = UserSubscription.objects.active_for_user(user)
    if subscription:
        subscription.refresh_period()
        return subscription
    subscription = UserSubscription.ensure_trial(user)
    if subscription:
        subscription.refresh_period()
    return subscription


def audit_dashboard(request):
    latest_audit = None
    findings = []
    metrics = []
    current_user = request.user if request.user.is_authenticated else None
    subscription = _resolve_subscription(current_user)
    remaining_audits = subscription.remaining_audits() if subscription else None

    if request.method == "POST":
        if not current_user:
            messages.error(request, "Sign in to run audits and manage your subscription.")
            return redirect("login")
        subscription = _resolve_subscription(current_user)
        if not subscription:
            messages.error(request, "Subscription could not be initialized. Try again later.")
            return redirect("audit-dashboard")
        if not subscription.has_capacity():
            messages.error(request, "You have reached your audit quota. Upgrade your plan to continue.")
            return redirect("pricing")
        website_id = (request.POST.get("website_id") or "").strip()
        url = (request.POST.get("url") or "").strip()
        name = (request.POST.get("name") or "").strip()

        website = None

        if website_id:
            website = Website.objects.filter(pk=website_id).first()
            if not website:
                messages.error(request, "Selected website could not be found.")

        if website is None and url:
            website, _ = Website.objects.get_or_create(url=url, defaults={"name": name})
            if name and website.name != name:
                website.name = name
                website.save(update_fields=["name"])

        if website is None and not url:
            messages.error(request, "Please choose a website or provide a new URL to audit.")
        elif website is not None:
            audit = run_audit(website, user=current_user)
            latest_audit = audit
            findings = list(audit.findings.all())
            metrics = list(audit.metrics.all())

            if audit.status == AuditRun.STATUS_COMPLETED:
                messages.success(request, "Audit completed successfully.")
                if subscription:
                    subscription.increment_usage()
            else:
                messages.warning(request, "The audit encountered an issue. Check the summary below for details.")

    audit_queryset = AuditRun.objects.select_related("website").prefetch_related("findings", "metrics").order_by("-created_at")

    if latest_audit is None:
        user_latest = audit_queryset.filter(created_by=current_user).first() if current_user else None
        latest_audit = user_latest or audit_queryset.first()
        if latest_audit:
            findings = list(latest_audit.findings.all())
            metrics = list(latest_audit.metrics.all())

    user_recent_audits = (
        audit_queryset.filter(created_by=current_user).only(
            "id", "status", "summary", "created_at", "website__name"
        )[:5]
        if current_user
        else []
    )

    recent_audits = audit_queryset.only(
        "id", "status", "summary", "created_at", "website__name"
    )[:5]
    websites = Website.objects.order_by("name", "url").all()

    usage_percent = None
    if subscription and getattr(subscription.plan, "audit_quota", 0):
        quota = subscription.plan.audit_quota or 0
        if quota > 0:
            usage_percent = min(100, int(round((subscription.audits_used / quota) * 100)))

    return render(
        request,
        "audit/dashboard.html",
        {
            "latest_audit": latest_audit,
            "findings": findings,
            "metrics": metrics,
            "recent_audits": recent_audits,
            "user_recent_audits": user_recent_audits,
            "websites": websites,
            "subscription": subscription,
            "remaining_audits": remaining_audits,
            "subscription_usage_percent": usage_percent,
            "plans": SubscriptionPlan.objects.filter(is_public=True, is_active=True).order_by("sort_order"),
            "trial_plan": SubscriptionPlan.get_trial_plan(),
        },
    )


def pricing(request):
    current_user = request.user if request.user.is_authenticated else None
    subscription = _resolve_subscription(current_user)
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by("sort_order")
    return render(
        request,
        "audit/pricing.html",
        {
            "plans": plans,
            "subscription": subscription,
        },
    )


def signup(request):
    if request.user.is_authenticated:
        return redirect("audit-dashboard")

    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        auth_login(request, user)
        UserSubscription.ensure_trial(user)
        messages.success(request, "Welcome aboard! Your free trial is ready.")
        return redirect("audit-dashboard")

    return render(request, "registration/signup.html", {"form": form})


@login_required
def create_checkout_session(request, slug):
    if request.method != "POST":
        return redirect("pricing")
    plan = get_object_or_404(SubscriptionPlan, slug=slug, is_active=True)
    user = request.user
    if plan.billing_interval == SubscriptionPlan.BILLING_TRIAL:
        UserSubscription.ensure_trial(user)
        messages.success(request, "Trial activated. Run your first audit now.")
        return redirect("audit-dashboard")
    Payment.objects.create(
        user=user,
        plan=plan,
        amount_cents=plan.price_cents,
        currency=plan.currency,
        provider="stripe",
        provider_reference=f"stub-{uuid.uuid4()}",
        status=Payment.STATUS_SUCCEEDED,
        metadata={"mode": plan.billing_interval},
    )
    existing = UserSubscription.objects.active_for_user(user)
    if existing and existing.plan_id == plan.id:
        existing.refresh_period()
    else:
        UserSubscription.start_new(user, plan)
    messages.success(request, f"You are now subscribed to {plan.name}.")
    return redirect("audit-dashboard")


@login_required
def download_audit_pdf(request, pk):
    audit = get_object_or_404(AuditRun.objects.select_related("website"), pk=pk)
    if not request.user.is_staff and audit.created_by_id != request.user.id:
        messages.error(request, "You do not have access to this report.")
        return redirect("audit-dashboard")
    pdf_bytes = generate_audit_pdf(audit)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f"attachment; filename=audit-{audit.pk}.pdf"
    return response
