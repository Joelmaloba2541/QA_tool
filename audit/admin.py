from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.db.models import Sum

from .models import (
    AuditFinding,
    AuditMetric,
    AuditRun,
    Payment,
    SubscriptionPlan,
    UserSubscription,
    Website,
)
from audit.services import run_audit


class QAAdminSite(admin.AdminSite):
    site_header = "QA Insights Administration"
    site_title = "QA Insights Admin"
    index_title = "Command Center"
    index_template = "admin/qa_dashboard.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("run-sample-audit/", self.admin_view(self.run_sample_audit), name="run-sample-audit"),
            path("reset-trials/", self.admin_view(self.reset_trials), name="reset-trials"),
        ]
        return custom + urls

    def index(self, request, extra_context=None):
        now = timezone.now()
        week_ago = now - timedelta(days=7)
        stats = {
            "recent_audits": AuditRun.objects.filter(created_at__gte=week_ago).count(),
            "active_subscriptions": UserSubscription.objects.filter(status=UserSubscription.STATUS_ACTIVE).count(),
            "weekly_revenue": (Payment.objects.filter(created_at__gte=week_ago, status=Payment.STATUS_SUCCEEDED).aggregate(total=Sum("amount_cents"))["total"] or 0) / 100,
        }
        extra_context = extra_context or {}
        extra_context.update({
            "stats": stats,
            "quick_actions": [
                {
                    "name": "Run sample audit",
                    "url": reverse(f"{self.name}:run-sample-audit"),
                    "description": "Trigger a demo audit against qa-tool-wg8f.onrender.com",
                },
                {
                    "name": "Reset free trials",
                    "url": reverse(f"{self.name}:reset-trials"),
                    "description": "Refresh trial usage for all users",
                },
                {
                    "name": "View recent payments",
                    "url": reverse(f"{self.name}:audit_payment_changelist"),
                    "description": "Inspect gateway receipts and offline invoices",
                },
            ],
        })
        return super().index(request, extra_context)

    def run_sample_audit(self, request):
        if request.method == "POST":
            website, _ = Website.objects.get_or_create(url="https://qa-tool-wg8f.onrender.com/")
            audit = run_audit(website, user=request.user if request.user.is_authenticated else None)
            self.message_user(request, f"Sample audit queued with status {audit.status}.")
            return HttpResponseRedirect(reverse(f"{self.name}:index"))
        context = dict(self.each_context(request), action="Run sample audit")
        return TemplateResponse(request, "admin/qa_confirm_action.html", context)

    def reset_trials(self, request):
        if request.method == "POST":
            count = UserSubscription.objects.filter(is_trial=True).update(audits_used=0)
            self.message_user(request, f"Reset usage for {count} trial subscriptions.")
            return HttpResponseRedirect(reverse(f"{self.name}:index"))
        context = dict(self.each_context(request), action="Reset trial usage")
        return TemplateResponse(request, "admin/qa_confirm_action.html", context)


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "created_at", "updated_at")
    search_fields = ("name", "url")


class AuditFindingInline(admin.TabularInline):
    model = AuditFinding
    extra = 0
    fields = ("category", "severity", "title")
    readonly_fields = fields


class AuditMetricInline(admin.TabularInline):
    model = AuditMetric
    extra = 0
    fields = ("label", "value")
    readonly_fields = fields


@admin.register(AuditRun)
class AuditRunAdmin(admin.ModelAdmin):
    list_display = ("website", "status", "score", "created_at", "created_by")
    list_filter = ("status", "created_at")
    search_fields = ("website__name", "website__url", "summary")
    date_hierarchy = "created_at"
    inlines = [AuditFindingInline, AuditMetricInline]
    actions = ["mark_completed", "recalculate_score"]

    @admin.action(description="Mark selected audits as completed")
    def mark_completed(self, request, queryset):
        updated = queryset.update(status=AuditRun.STATUS_COMPLETED)
        self.message_user(request, f"{updated} audits marked as completed.")

    @admin.action(description="Recalculate audit score")
    def recalculate_score(self, request, queryset):
        recalculated = 0
        for run in queryset.select_related("website"):
            metrics = list(run.metrics.all())
            if not metrics:
                continue
            numeric_values = []
            for metric in metrics:
                try:
                    numeric_values.append(float(Decimal(metric.value)))
                except (InvalidOperation, TypeError, ValueError):
                    continue
            if not numeric_values:
                continue
            new_score = max(0, min(100, int(round(sum(numeric_values) / len(numeric_values)))))
            run.score = new_score
            run.save(update_fields=["score", "updated_at"])
            recalculated += 1
        if recalculated:
            self.message_user(request, f"Recalculated {recalculated} audit scores.")
        else:
            self.message_user(request, "No metrics available to recalculate.", level=messages.WARNING)


@admin.register(AuditFinding)
class AuditFindingAdmin(admin.ModelAdmin):
    list_display = ("audit", "category", "severity", "title")
    list_filter = ("category", "severity")
    search_fields = ("title", "description")


@admin.register(AuditMetric)
class AuditMetricAdmin(admin.ModelAdmin):
    list_display = ("audit", "label", "value")
    search_fields = ("label", "value")


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "billing_interval", "display_price", "audit_quota", "is_active", "is_public")
    list_filter = ("billing_interval", "is_active", "is_public")
    search_fields = ("name", "description")
    ordering = ("sort_order",)
    actions = ["activate_plans", "deactivate_plans"]

    @admin.action(description="Activate selected plans")
    def activate_plans(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} plans activated.")

    @admin.action(description="Deactivate selected plans")
    def deactivate_plans(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} plans deactivated.")


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "started_at", "current_period_end", "audits_used", "is_trial")
    list_filter = ("status", "is_trial", "plan__billing_interval")
    search_fields = ("user__username", "user__email", "plan__name")
    date_hierarchy = "started_at"
    actions = ["reset_usage", "refresh_periods"]

    @admin.action(description="Reset audit usage to zero")
    def reset_usage(self, request, queryset):
        updated = queryset.update(audits_used=0)
        self.message_user(request, f"Reset usage for {updated} subscriptions.")

    @admin.action(description="Refresh billing periods")
    def refresh_periods(self, request, queryset):
        refreshed = 0
        for subscription in queryset.select_related("plan"):
            subscription.refresh_period()
            refreshed += 1
        self.message_user(request, f"Refreshed periods for {refreshed} subscriptions.")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "amount_cents", "currency", "status", "provider", "created_at")
    list_filter = ("status", "provider", "currency")
    search_fields = ("user__username", "user__email", "provider_reference")
    actions = ["mark_succeeded", "mark_failed"]

    @admin.action(description="Mark selected payments as succeeded")
    def mark_succeeded(self, request, queryset):
        updated = queryset.update(status=Payment.STATUS_SUCCEEDED)
        self.message_user(request, f"{updated} payments marked as succeeded.")

    @admin.action(description="Mark selected payments as failed")
    def mark_failed(self, request, queryset):
        updated = queryset.update(status=Payment.STATUS_FAILED)
        self.message_user(request, f"{updated} payments marked as failed.")


qa_admin_site = QAAdminSite(name="qa_admin")
qa_admin_site.register(Website, WebsiteAdmin)
qa_admin_site.register(AuditRun, AuditRunAdmin)
qa_admin_site.register(AuditFinding, AuditFindingAdmin)
qa_admin_site.register(AuditMetric, AuditMetricAdmin)
qa_admin_site.register(SubscriptionPlan, SubscriptionPlanAdmin)
qa_admin_site.register(UserSubscription, UserSubscriptionAdmin)
qa_admin_site.register(Payment, PaymentAdmin)
