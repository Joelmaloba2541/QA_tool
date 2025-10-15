from unittest.mock import patch

from django.test import TestCase

from audit.models import AuditFinding, AuditMetric, AuditRun, Website
from audit.services import ParsedPage, run_audit

# Create your tests here.


class RunAuditTests(TestCase):
    def setUp(self):
        self.website = Website.objects.create(name="Example", url="https://example.com")

    @patch("audit.services._sample_link_health")
    @patch("audit.services._parse_html")
    @patch("audit.services._safe_request")
    def test_run_audit_successful_flow(self, mock_safe_request, mock_parse_html, mock_sample_link_health):
        mock_safe_request.side_effect = [
            (200, b"<html></html>", 120),
            (200, b"", 5),
        ]
        mock_parse_html.return_value = ParsedPage(
            url="https://example.com",
            title="Example Page",
            meta={"description": "desc", "link::icon": "/favicon.ico"},
            links=[],
            images=[("image.jpg", "alt text")],
            headings=[("h1", "Heading")],
            forms=0,
        )
        mock_sample_link_health.return_value = {}

        audit = run_audit(self.website)

        self.assertEqual(audit.status, AuditRun.STATUS_COMPLETED)
        self.assertEqual(audit.summary, "Example Page")
        self.assertEqual(audit.score, 100)
        self.assertEqual(audit.response_time_ms, 120)
        self.assertEqual(audit.content_length, len(b"<html></html>"))
        self.assertEqual(audit.metadata["status"], 200)
        self.assertEqual(AuditRun.objects.count(), 1)
        self.assertEqual(AuditFinding.objects.count(), 0)
        metrics = AuditMetric.objects.filter(audit=audit).values_list("label", flat=True)
        self.assertCountEqual(
            metrics,
            [
                "Response status",
                "Response time (ms)",
                "HTML bytes",
                "Total links parsed",
                "Images parsed",
            ],
        )

    @patch("audit.services._safe_request", side_effect=RuntimeError("boom"))
    def test_run_audit_handles_failure(self, mock_safe_request):
        audit = run_audit(self.website)

        self.assertEqual(audit.status, AuditRun.STATUS_FAILED)
        self.assertTrue(audit.summary.startswith("Audit failed:"))
        self.assertEqual(AuditRun.objects.count(), 1)
        self.assertEqual(AuditFinding.objects.count(), 0)
        self.assertEqual(AuditMetric.objects.count(), 0)
