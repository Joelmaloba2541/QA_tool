import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from urllib.parse import urlparse

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone

from audit.models import AuditRun, Payment, SubscriptionPlan, UserSubscription, Website
from audit.services import generate_audit_pdf, run_audit


def _complete_subscription(request, user, plan, *, provider="manual", payment_reference="", metadata=None):
    metadata = metadata or {}
    if plan.billing_interval == SubscriptionPlan.BILLING_TRIAL:
        UserSubscription.ensure_trial(user)
        messages.success(request, "Trial activated. Run your first audit now.")
        return

    requires_payment = plan.price_cents > 0
    if requires_payment and not payment_reference:
        messages.error(request, "Payment reference required for paid plans")
        raise ValueError("Payment reference required for paid plans")

    if requires_payment:
        Payment.objects.create(
            user=user,
            plan=plan,
            amount_cents=plan.price_cents,
            currency=plan.currency,
            provider=provider,
            provider_reference=payment_reference or f"ref-{uuid.uuid4()}",
            status=Payment.STATUS_SUCCEEDED,
            metadata={"mode": plan.billing_interval, **metadata},
        )

    existing = UserSubscription.objects.active_for_user(user)
    if existing and existing.plan_id == plan.id:
        existing.refresh_period()
    else:
        UserSubscription.start_new(user, plan)


def payment_checkout(request, slug):
    if request.method not in {"GET", "POST"}:
        return redirect("pricing")
    plan = get_object_or_404(SubscriptionPlan, slug=slug, is_active=True)
    user = request.user
    if not user.is_authenticated:
        messages.info(request, "Sign in to activate a subscription.")
        return redirect(f"{reverse('login')}?next={request.path}")

    existing = UserSubscription.objects.active_for_user(user)

    if request.method == "POST":
        provider = request.POST.get("provider", "manual")
        payment_reference = (request.POST.get("payment_reference") or "").strip()
        payment_token = (request.POST.get("payment_token") or "").strip()
        if provider == "inline":
            payment_reference = payment_reference or payment_token
        try:
            _complete_subscription(
                request,
                user,
                plan,
                provider="inline" if provider == "inline" else "manual",
                payment_reference=payment_reference,
                metadata={"source": provider},
            )
        except ValueError:
            messages.error(request, "Add a payment reference before continuing.")
            return redirect("payment-checkout", slug=plan.slug)
        messages.success(request, f"You are now subscribed to {plan.name}.")
        return redirect("audit-dashboard")

    return render(
        request,
        "audit/payment_checkout.html",
        {
            "plan": plan,
            "existing": existing,
            "gateway_url": reverse("payment-gateway", args=[plan.slug]),
        },
    )


def payment_gateway_redirect(request, slug):
    plan = get_object_or_404(SubscriptionPlan, slug=slug, is_active=True)
    if not request.user.is_authenticated:
        messages.info(request, "Sign in to proceed with payment.")
        return redirect(f"{reverse('login')}?next={request.path}")
    request.session["gateway_plan_slug"] = plan.slug
    request.session["gateway_next"] = request.GET.get("next")
    context = {
        "plan": plan,
        "callback_url": f"{reverse('payment-gateway-callback')}?status=success",
        "cancel_url": f"{reverse('payment-gateway-callback')}?status=cancelled",
    }
    return render(request, "audit/payment_gateway_redirect.html", context)


def payment_gateway_callback(request):
    status = request.GET.get("status")
    plan_slug = request.session.pop("gateway_plan_slug", None)
    redirect_url = request.session.pop("gateway_next", None) or reverse("pricing")
    if not plan_slug:
        messages.error(request, "Your payment session expired. Try again.")
        return redirect("pricing")
    plan = get_object_or_404(SubscriptionPlan, slug=plan_slug, is_active=True)
    user = request.user
    if not user.is_authenticated:
        messages.error(request, "Sign in to finalize your subscription.")
        return redirect("login")
    if status != "success":
        messages.warning(request, "Payment was cancelled. You can try again anytime.")
        return redirect(redirect_url)
    reference = f"gateway-{uuid.uuid4()}"
    _complete_subscription(
        request,
        user,
        plan,
        provider="gateway",
        payment_reference=reference,
        metadata={"provider": "mock-gateway"},
    )
    messages.success(request, f"Payment confirmed. {plan.name} is now active.")
    return redirect("audit-dashboard")

TLD_TO_ISO = {
    "com": "US",
    "net": "US",
    "org": "US",
    "io": "GB",
    "co": "US",
    "ai": "US",
    "app": "US",
    "dev": "US",
    "us": "US",
    "ca": "CA",
    "uk": "GB",
    "ie": "IE",
    "de": "DE",
    "fr": "FR",
    "nl": "NL",
    "es": "ES",
    "it": "IT",
    "za": "ZA",
    "ng": "NG",
    "ke": "KE",
    "in": "IN",
    "sg": "SG",
    "au": "AU",
    "nz": "NZ",
    "br": "BR",
    "ar": "AR",
    "mx": "MX",
    "jp": "JP",
}

ISO_MARKERS = {
    "US": {"name": "North America", "coords": [37.0902, -95.7129]},
    "CA": {"name": "Canada", "coords": [56.1304, -106.3468]},
    "GB": {"name": "United Kingdom", "coords": [55.3781, -3.436]},
    "IE": {"name": "Ireland", "coords": [53.4129, -8.2439]},
    "DE": {"name": "Germany", "coords": [51.1657, 10.4515]},
    "FR": {"name": "France", "coords": [46.2276, 2.2137]},
    "NL": {"name": "Netherlands", "coords": [52.1326, 5.2913]},
    "ES": {"name": "Spain", "coords": [40.4637, -3.7492]},
    "IT": {"name": "Italy", "coords": [41.8719, 12.5674]},
    "ZA": {"name": "South Africa", "coords": [-30.5595, 22.9375]},
    "NG": {"name": "Nigeria", "coords": [9.082, 8.6753]},
    "KE": {"name": "Kenya", "coords": [-0.0236, 37.9062]},
    "IN": {"name": "India", "coords": [20.5937, 78.9629]},
    "SG": {"name": "Singapore", "coords": [1.3521, 103.8198]},
    "AU": {"name": "Australia", "coords": [-25.2744, 133.7751]},
    "NZ": {"name": "New Zealand", "coords": [-40.9006, 174.886]},
    "BR": {"name": "Brazil", "coords": [-14.235, -51.9253]},
    "AR": {"name": "Argentina", "coords": [-38.4161, -63.6167]},
    "MX": {"name": "Mexico", "coords": [23.6345, -102.5528]},
    "JP": {"name": "Japan", "coords": [36.2048, 138.2529]},
}


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
        if not (current_user.is_staff or subscription.has_capacity()):
            messages.error(
                request,
                "Your complimentary audit is used up. Upgrade now to unlock deeper insights and unlimited reruns.",
            )
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
    websites = list(Website.objects.order_by("name", "url").all())

    status_counts = Counter(audit_queryset.values_list("status", flat=True))
    chart_status_counts = [
        {"status": status, "count": count}
        for status, count in status_counts.items()
    ]

    trend_values = list(
        audit_queryset.values("created_at", "score").order_by("-created_at")[:12]
    )
    chart_score_series = [
        {
            "timestamp": value["created_at"].strftime("%Y-%m-%d"),
            "score": value["score"],
        }
        for value in reversed(trend_values)
        if value["created_at"]
    ]

    plan_totals = (
        SubscriptionPlan.objects.filter(is_active=True)
        .annotate(
            active_count=Count(
                "subscriptions",
                filter=Q(subscriptions__status=UserSubscription.STATUS_ACTIVE),
            )
        )
        .values("name", "slug", "active_count")
    )
    chart_plan_breakdown = [
        {"name": entry["name"], "slug": entry["slug"], "count": entry["active_count"] or 0}
        for entry in plan_totals
    ]

    plans_qs = SubscriptionPlan.objects.filter(is_public=True, is_active=True).order_by("sort_order")
    plans = list(plans_qs)
    feature_catalog: list[str] = []
    for plan in plans:
        for feature in plan.features or []:
            if feature not in feature_catalog:
                feature_catalog.append(feature)
    plan_feature_matrix = []
    for feature in feature_catalog:
        plan_feature_matrix.append(
            {
                "feature": feature,
                "plans": [
                    {
                        "slug": plan.slug,
                        "name": plan.name,
                        "available": feature in (plan.features or []),
                    }
                    for plan in plans
                ],
            }
        )

    region_counts = defaultdict(int)
    for site in websites:
        parsed = urlparse(site.url)
        host = parsed.hostname or ""
        tld = host.split(".")[-1].lower() if host else ""
        iso_code = TLD_TO_ISO.get(tld)
        if iso_code:
            region_counts[iso_code] += 1

    region_markers = []
    for iso_code, count in region_counts.items():
        marker_meta = ISO_MARKERS.get(iso_code)
        if not marker_meta:
            continue
        region_markers.append(
            {
                "name": marker_meta["name"],
                "coords": marker_meta["coords"],
                "count": count,
                "iso": iso_code,
            }
        )

    region_summary = [
        {
            "iso": iso_code,
            "name": ISO_MARKERS.get(iso_code, {}).get("name", iso_code),
            "count": count,
        }
        for iso_code, count in sorted(region_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    aggregates = audit_queryset.aggregate(
        avg_score=Avg("score"),
        avg_response=Avg("response_time_ms"),
    )
    total_audits = audit_queryset.count()
    completed_audits = status_counts.get(AuditRun.STATUS_COMPLETED, 0)
    failed_audits = status_counts.get(AuditRun.STATUS_FAILED, 0)
    completion_rate = int(round((completed_audits / total_audits) * 100)) if total_audits else 0

    # Weekly audit velocity (last 8 weeks)
    now = timezone.now()
    start_of_week = now - timedelta(days=now.weekday())
    audit_velocity = []
    for i in range(7, -1, -1):
        week_start = start_of_week - timedelta(weeks=i)
        week_end = week_start + timedelta(days=7)
        count = audit_queryset.filter(created_at__gte=week_start, created_at__lt=week_end).count()
        audit_velocity.append({"week": week_start.strftime("%b %d"), "count": count})

    # Recent timeline events (audits, payments, subscriptions)
    timeline_events = []
    for audit in audit_queryset.select_related("website")[:5]:
        timeline_events.append(
            {
                "timestamp": audit.created_at,
                "type": "audit",
                "label": f"Audit for {audit.website.name or audit.website.url}",
                "meta": audit.status.title(),
            }
        )
    for payment in Payment.objects.filter(status=Payment.STATUS_SUCCEEDED).select_related("plan")[:5]:
        timeline_events.append(
            {
                "timestamp": payment.created_at,
                "type": "payment",
                "label": f"Payment for {payment.plan.name}",
                "meta": payment.display_amount if hasattr(payment, "display_amount") else payment.amount_cents / 100,
            }
        )
    for subscription_event in UserSubscription.objects.filter(status=UserSubscription.STATUS_ACTIVE).select_related("plan")[:5]:
        timeline_events.append(
            {
                "timestamp": subscription_event.started_at,
                "type": "subscription",
                "label": f"{subscription_event.plan.name} activated",
                "meta": subscription_event.user.get_username(),
            }
        )
    timeline_events.sort(key=lambda item: item["timestamp"], reverse=True)
    timeline_events = timeline_events[:10]

    revenue_data = Payment.objects.filter(status=Payment.STATUS_SUCCEEDED).aggregate(total=Sum("amount_cents"))
    total_revenue = (revenue_data["total"] or 0) / 100

    smart_suggestions = []
    if completion_rate < 85:
        smart_suggestions.append("Improve audit playbooks to raise completion reliability above 90%.")
    if (aggregates.get("avg_response") or 0) > 1200:
        smart_suggestions.append("Response times are high; consider enabling CDN caching on key sites.")
    if not smart_suggestions:
        smart_suggestions.append("Fantastic performance! Schedule recurring audits to maintain momentum.")

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
            "chart_status_counts": chart_status_counts,
            "chart_score_series": chart_score_series,
            "chart_plan_breakdown": chart_plan_breakdown,
            "region_series": dict(region_counts),
            "region_markers": region_markers,
            "region_summary": region_summary,
            "audit_velocity": audit_velocity,
            "timeline_events": timeline_events,
            "total_revenue": total_revenue,
            "smart_suggestions": smart_suggestions,
            "analytics_totals": {
                "total": total_audits,
                "completed": completed_audits,
                "failed": failed_audits,
                "completion_rate": completion_rate,
                "avg_score": round(aggregates.get("avg_score") or 0, 1),
                "avg_response": int(aggregates.get("avg_response") or 0),
            },
            "plans": plans,
            "plan_feature_matrix": plan_feature_matrix,
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
    existing = UserSubscription.objects.active_for_user(user)

    if existing and existing.plan_id == plan.id:
        messages.info(request, "You are already on this plan.")
        return redirect("pricing")

    payment_reference = (request.POST.get("payment_reference") or "").strip()
    requires_payment = plan.price_cents > 0 and (existing is None or existing.plan_id != plan.id)
    if requires_payment and not payment_reference:
        messages.error(request, "Provide a payment reference before activating a paid plan.")
        return redirect("pricing")

    if plan.billing_interval == SubscriptionPlan.BILLING_TRIAL:
        UserSubscription.ensure_trial(user)
        messages.success(request, "Trial activated. Run your first audit now.")
        return redirect("audit-dashboard")
    try:
        _complete_subscription(
            request,
            user,
            plan,
            provider="manual",
            payment_reference=payment_reference,
            metadata={"source": "legacy-checkout"},
        )
    except ValueError:
        messages.error(request, "Provide a payment reference before activating a paid plan.")
        return redirect("pricing")
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
