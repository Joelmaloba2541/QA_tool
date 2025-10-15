from django.contrib import messages
from django.shortcuts import render

from audit.models import AuditRun, Website
from audit.services import run_audit

# Create your views here.

def audit_dashboard(request):
    latest_audit = None
    findings = []
    metrics = []

    if request.method == "POST":
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
            audit = run_audit(website)
            latest_audit = audit
            findings = list(audit.findings.all())
            metrics = list(audit.metrics.all())

            if audit.status == AuditRun.STATUS_COMPLETED:
                messages.success(request, "Audit completed successfully.")
            else:
                messages.warning(request, "The audit encountered an issue. Check the summary below for details.")

    if latest_audit is None:
        latest_audit = (
            AuditRun.objects.select_related("website")
            .prefetch_related("findings", "metrics")
            .order_by("-created_at")
            .first()
        )
        if latest_audit:
            findings = list(latest_audit.findings.all())
            metrics = list(latest_audit.metrics.all())

    recent_audits = (
        AuditRun.objects.select_related("website").order_by("-created_at").only(
            "id", "status", "summary", "created_at", "website__name"
        )[:5]
    )
    websites = Website.objects.order_by("name", "url").all()

    return render(
        request,
        "audit/dashboard.html",
        {
            "latest_audit": latest_audit,
            "findings": findings,
            "metrics": metrics,
            "recent_audits": recent_audits,
            "websites": websites,
        },
    )
