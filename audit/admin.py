from django.contrib import admin

from .models import AuditFinding, AuditMetric, AuditRun, Payment, SubscriptionPlan, UserSubscription, Website


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "created_at", "updated_at")
    search_fields = ("name", "url")


@admin.register(AuditRun)
class AuditRunAdmin(admin.ModelAdmin):
    list_display = ("website", "status", "score", "created_at", "created_by")
    list_filter = ("status", "created_at")
    search_fields = ("website__name", "website__url", "summary")
    date_hierarchy = "created_at"


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


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "started_at", "current_period_end", "audits_used", "is_trial")
    list_filter = ("status", "is_trial", "plan__billing_interval")
    search_fields = ("user__username", "user__email", "plan__name")
    date_hierarchy = "started_at"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "amount_cents", "currency", "status", "provider", "created_at")
    list_filter = ("status", "provider", "currency")
    search_fields = ("user__username", "user__email", "provider_reference")
