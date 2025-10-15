from django.db import models


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
