from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Website(models.Model):
    name = models.CharField(max_length=255, blank=True)
    url = models.URLField(unique=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or self.url


class AuditRun(models.Model):
    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="audits")
    url = models.URLField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_runs",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    summary = models.TextField(blank=True)
    score = models.PositiveIntegerField(default=0)
    response_time_ms = models.PositiveIntegerField(default=0)
    content_length = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Audit {self.website} @ {self.created_at:%Y-%m-%d %H:%M}"


class AuditFinding(models.Model):
    SEVERITY_LOW = "low"
    SEVERITY_MEDIUM = "medium"
    SEVERITY_HIGH = "high"
    SEVERITY_CHOICES = [
        (SEVERITY_LOW, "Low"),
        (SEVERITY_MEDIUM, "Medium"),
        (SEVERITY_HIGH, "High"),
    ]

    audit = models.ForeignKey(AuditRun, on_delete=models.CASCADE, related_name="findings")
    category = models.CharField(max_length=100)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    title = models.CharField(max_length=255)
    description = models.TextField()
    recommendation = models.TextField()

    def __str__(self):
        return f"{self.audit.website} - {self.title}"


class AuditMetric(models.Model):
    audit = models.ForeignKey(AuditRun, on_delete=models.CASCADE, related_name="metrics")
    label = models.CharField(max_length=255)
    value = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.audit.website} - {self.label}"


class SubscriptionPlan(models.Model):
    BILLING_TRIAL = "trial"
    BILLING_MONTHLY = "monthly"
    BILLING_YEARLY = "yearly"
    BILLING_LIFETIME = "lifetime"
    BILLING_CHOICES = [
        (BILLING_TRIAL, "Trial"),
        (BILLING_MONTHLY, "Monthly"),
        (BILLING_YEARLY, "Yearly"),
        (BILLING_LIFETIME, "Lifetime"),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    price_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=10, default="USD")
    billing_interval = models.CharField(max_length=20, choices=BILLING_CHOICES, default=BILLING_MONTHLY)
    trial_days = models.PositiveIntegerField(default=7)
    audit_quota = models.PositiveIntegerField(null=True, blank=True)
    features = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price_cents"]

    def __str__(self):
        return self.name

    def display_price(self):
        if self.price_cents == 0:
            return "Free"
        if self.currency.upper() == "USD":
            amount = self.price_cents / 100
            if self.price_cents % 100:
                return f"${amount:.2f}"
            return f"${int(amount)}"
        if self.price_cents % 100:
            return f"{self.currency} {self.price_cents / 100:.2f}"
        return f"{self.currency} {self.price_cents // 100}"

    def period_delta(self):
        if self.billing_interval == self.BILLING_TRIAL:
            return timedelta(days=self.trial_days or 7)
        if self.billing_interval == self.BILLING_YEARLY:
            return timedelta(days=365)
        if self.billing_interval == self.BILLING_LIFETIME:
            return timedelta(days=3650)
        return timedelta(days=30)

    @classmethod
    def get_trial_plan(cls):
        return cls.objects.filter(slug="free-trial").first()

    @classmethod
    def bootstrap_defaults(cls):
        defaults = [
            {
                "slug": "free-trial",
                "name": "Free Trial",
                "description": "Run your first audit and experience automated QA reporting.",
                "price_cents": 0,
                "billing_interval": cls.BILLING_TRIAL,
                "trial_days": 7,
                "audit_quota": 1,
                "is_public": False,
                "sort_order": 0,
                "features": [
                    "Single guided audit",
                    "Full PDF export",
                    "Insights dashboard access",
                ],
            },
            {
                "slug": "growth",
                "name": "Growth",
                "description": "For product teams scaling continuous QA insights.",
                "price_cents": 4900,
                "billing_interval": cls.BILLING_MONTHLY,
                "audit_quota": 20,
                "is_public": True,
                "sort_order": 1,
                "features": [
                    "20 audits per month",
                    "Unlimited PDF exports",
                    "Priority inbox support",
                    "Team workspace analytics",
                ],
            },
            {
                "slug": "scale",
                "name": "Scale",
                "description": "Unlimited QA automation for digital agencies and enterprises.",
                "price_cents": 12900,
                "billing_interval": cls.BILLING_MONTHLY,
                "audit_quota": None,
                "is_public": True,
                "sort_order": 2,
                "features": [
                    "Unlimited audits",
                    "Advanced remediation playbooks",
                    "Dedicated success architect",
                    "White-label reporting",
                ],
            },
        ]
        for data in defaults:
            slug = data["slug"]
            obj, created = cls.objects.get_or_create(slug=slug, defaults=data)
            if not created:
                update_fields = {k: v for k, v in data.items() if getattr(obj, k) != v}
                if update_fields:
                    for key, val in update_fields.items():
                        setattr(obj, key, val)
                    obj.save()


class UserSubscriptionManager(models.Manager):
    def active_for_user(self, user):
        now = timezone.now()
        return (
            self.filter(user=user, status=UserSubscription.STATUS_ACTIVE)
            .filter(Q(current_period_end__isnull=True) | Q(current_period_end__gte=now))
            .order_by("-current_period_end", "-created_at")
            .first()
        )


class UserSubscription(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_CANCELLED = "cancelled"
    STATUS_PAST_DUE = "past_due"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_PAST_DUE, "Past due"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    started_at = models.DateTimeField(default=timezone.now)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    audits_used = models.PositiveIntegerField(default=0)
    is_trial = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserSubscriptionManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} → {self.plan.name}"

    def refresh_period(self):
        if not self.plan:
            return
        now = timezone.now()
        if self.current_period_end and self.current_period_end > now:
            return
        delta = self.plan.period_delta()
        self.current_period_start = now
        self.current_period_end = now + delta
        self.audits_used = 0
        self.save(update_fields=["current_period_start", "current_period_end", "audits_used", "updated_at"])

    def remaining_audits(self):
        if self.plan.audit_quota is None:
            return None
        value = self.plan.audit_quota - self.audits_used
        return max(value, 0)

    def increment_usage(self):
        quota = self.plan.audit_quota
        if quota is None or self.audits_used < quota:
            self.audits_used += 1
            self.save(update_fields=["audits_used", "updated_at"])

    def has_capacity(self):
        quota = self.plan.audit_quota
        if quota is None:
            return True
        return self.audits_used < quota

    @classmethod
    def ensure_trial(cls, user):
        plan = SubscriptionPlan.get_trial_plan()
        if not plan:
            plan = SubscriptionPlan.objects.filter(billing_interval=SubscriptionPlan.BILLING_TRIAL).first()
        if not plan:
            return None
        existing = cls.objects.filter(user=user, plan=plan, status=cls.STATUS_ACTIVE).order_by("-created_at").first()
        if existing:
            return existing
        now = timezone.now()
        subscription = cls.objects.create(
            user=user,
            plan=plan,
            status=cls.STATUS_ACTIVE,
            started_at=now,
            current_period_start=now,
            current_period_end=now + plan.period_delta(),
            audits_used=AuditRun.objects.filter(created_by=user).count(),
            is_trial=True,
        )
        return subscription

    @classmethod
    def start_new(cls, user, plan):
        now = timezone.now()
        period_end = now + plan.period_delta() if plan.billing_interval != SubscriptionPlan.BILLING_LIFETIME else None
        instance = cls.objects.create(
            user=user,
            plan=plan,
            status=cls.STATUS_ACTIVE,
            started_at=now,
            current_period_start=now,
            current_period_end=period_end,
            audits_used=0,
            is_trial=plan.billing_interval == SubscriptionPlan.BILLING_TRIAL,
        )
        return instance


class Payment(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="payments")
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=10, default="USD")
    provider = models.CharField(max_length=50, default="manual")
    provider_reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} → {self.plan.name} ({self.status})"

    @property
    def display_amount(self):
        amount = self.amount_cents / 100
        if self.currency.upper() == "USD":
            return f"${amount:,.2f}"
        return f"{self.currency} {amount:,.2f}"
