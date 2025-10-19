import json
import re
import ssl
import time
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from django.utils.text import Truncator
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import AuditFinding, AuditMetric, AuditRun, Website


@dataclass
class ParsedPage:
    url: str
    title: Optional[str] = None
    meta: Dict[str, str] = field(default_factory=dict)
    links: List[str] = field(default_factory=list)
    images: List[Tuple[str, str]] = field(default_factory=list)  # (src, alt)
    headings: List[Tuple[str, str]] = field(default_factory=list)  # (tag, text)
    forms: int = 0


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.page = ParsedPage(url="")
        self._current_data_stack: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "title":
            self._current_data_stack.append("title")
        elif tag == "a":
            href = attrs_dict.get("href")
            if href:
                self.page.links.append(href)
        elif tag == "img":
            src = attrs_dict.get("src", "")
            alt = attrs_dict.get("alt", "")
            self.page.images.append((src, alt))
        elif tag in {"h1", "h2", "h3"}:
            self._current_data_stack.append(tag)
        elif tag == "form":
            self.page.forms += 1
        elif tag == "meta":
            name = attrs_dict.get("name") or attrs_dict.get("property")
            content = attrs_dict.get("content")
            if name and content:
                self.page.meta[name.lower()] = content
        elif tag == "link":
            rel = attrs_dict.get("rel")
            href = attrs_dict.get("href")
            if rel and href:
                self.page.meta.setdefault(f"link::{','.join(rel)}", href)

    def handle_endtag(self, tag):
        if self._current_data_stack and self._current_data_stack[-1] == tag:
            self._current_data_stack.pop()

    def handle_data(self, data):
        if not self._current_data_stack:
            return
        key = self._current_data_stack[-1]
        data = data.strip()
        if not data:
            return
        if key == "title":
            self.page.title = (self.page.title or "") + data
        else:
            self.page.headings.append((key, data))


def _safe_request(url: str, timeout: int = 15) -> Tuple[int, bytes, float]:
    request = urllib.request.Request(url, headers={"User-Agent": "QA-Tool/1.0"})
    ssl_context = ssl.create_default_context()
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
        body = response.read()
        status = getattr(response, "status", response.getcode())
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return status, body, elapsed_ms


def _parse_html(content: bytes, url: str) -> ParsedPage:
    parser = _PageParser()
    parser.page.url = url
    try:
        parser.feed(content.decode("utf-8", errors="ignore"))
    finally:
        parser.close()
    return parser.page


def _absolutize_links(base_url: str, links: Iterable[str]) -> List[str]:
    abs_links: List[str] = []
    for link in links:
        if not link:
            continue
        link = link.strip()
        if link.startswith("javascript:"):
            continue
        abs_links.append(urljoin(base_url, link))
    return abs_links


def _sample_link_health(base_url: str, links: List[str], limit: int = 5) -> Dict[str, int]:
    samples = {}
    for link in links[:limit]:
        try:
            status, _, _ = _safe_request(link)
            samples[link] = status
        except Exception:
            samples[link] = 0
    return samples


def _evaluate_findings(page: ParsedPage, response_status: int, response_time_ms: int, robots_status: Optional[int], link_statuses: Dict[str, int]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    severity = AuditFinding.SEVERITY_MEDIUM if response_status >= 400 else AuditFinding.SEVERITY_LOW
    if response_status >= 400 or response_status == 0:
        findings.append(
            {
                "category": "availability",
                "severity": AuditFinding.SEVERITY_HIGH,
                "title": "Homepage is unreachable",
                "description": f"The main URL returned status {response_status}.",
                "recommendation": "Verify hosting availability and ensure the server returns 200 OK for the homepage.",
            }
        )

    if response_time_ms > 2000:
        findings.append(
            {
                "category": "performance",
                "severity": AuditFinding.SEVERITY_MEDIUM,
                "title": "Slow initial response",
                "description": f"Measured response time {response_time_ms}ms exceeds the 2s threshold.",
                "recommendation": "Optimize server-side rendering, add caching, and compress assets to improve TTFB.",
            }
        )

    if not page.meta.get("description"):
        findings.append(
            {
                "category": "seo",
                "severity": AuditFinding.SEVERITY_MEDIUM,
                "title": "Missing meta description",
                "description": "The page does not define a meta description tag.",
                "recommendation": "Add a concise, keyword-rich meta description under 160 characters to improve SERP visibility.",
            }
        )

    if not any(key.startswith("link::icon") or "icon" in key for key in page.meta):
        findings.append(
            {
                "category": "branding",
                "severity": AuditFinding.SEVERITY_LOW,
                "title": "No favicon detected",
                "description": "Browsers did not detect a favicon link element.",
                "recommendation": "Add a `<link rel=\"icon\">` tag pointing to a favicon for brand recognition.",
            }
        )

    if not any(tag == "h1" for tag, _ in page.headings):
        findings.append(
            {
                "category": "structure",
                "severity": AuditFinding.SEVERITY_LOW,
                "title": "No H1 heading",
                "description": "The page markup is missing a primary `<h1>` heading.",
                "recommendation": "Provide a unique H1 heading describing the page contents.",
            }
        )

    missing_alt = [src for src, alt in page.images if not alt.strip()]
    if missing_alt:
        findings.append(
            {
                "category": "accessibility",
                "severity": AuditFinding.SEVERITY_MEDIUM,
                "title": "Images without alternative text",
                "description": f"Detected {len(missing_alt)} image(s) missing alt descriptions.",
                "recommendation": "Add meaningful `alt` attributes to all informative images to comply with WCAG guidelines.",
            }
        )

    broken_links = [link for link, status in link_statuses.items() if status >= 400 or status == 0]
    if broken_links:
        truncated_links = ", ".join(Truncator(link).chars(80) for link in broken_links[:3])
        findings.append(
            {
                "category": "links",
                "severity": AuditFinding.SEVERITY_HIGH,
                "title": "Broken links detected",
                "description": f"Sampled links returned errors: {truncated_links}.",
                "recommendation": "Update or remove broken links to maintain trust and SEO health.",
            }
        )

    if robots_status is None:
        findings.append(
            {
                "category": "seo",
                "severity": AuditFinding.SEVERITY_LOW,
                "title": "robots.txt not reachable",
                "description": "Crawler directives file `/robots.txt` was not found or returned an error.",
                "recommendation": "Provide a robots.txt to guide search engine crawlers and list your sitemap.",
            }
        )

    return findings


def _calculate_score(page: ParsedPage, findings: List[Dict[str, str]]) -> int:
    base = 99
    penalties = {
        AuditFinding.SEVERITY_LOW: 5,
        AuditFinding.SEVERITY_MEDIUM: 10,
        AuditFinding.SEVERITY_HIGH: 20,
    }
    for finding in findings:
        base -= penalties.get(finding["severity"], 5)
    return max(0, base)


def run_audit(website: Website, url: Optional[str] = None, user=None) -> AuditRun:
    target_url = url or website.url
    audit = AuditRun.objects.create(website=website, url=target_url, created_by=user)

    try:
        status, body, response_time = _safe_request(target_url)
        page = _parse_html(body, target_url)
        absolute_links = _absolutize_links(target_url, page.links)
        link_statuses = _sample_link_health(target_url, absolute_links)

        robots_status: Optional[int]
        try:
            robots_status, _, _ = _safe_request(urljoin(target_url, "/robots.txt"))
            if robots_status >= 400:
                robots_status = None
        except Exception:
            robots_status = None

        findings = _evaluate_findings(page, status, response_time, robots_status, link_statuses)
        score = _calculate_score(page, findings)

        audit.status = AuditRun.STATUS_COMPLETED
        audit.summary = page.title or "Untitled page"
        audit.score = score
        audit.response_time_ms = response_time
        audit.content_length = len(body)
        audit.metadata = {
            "status": status,
            "title": page.title,
            "meta": page.meta,
            "forms": page.forms,
            "headings": page.headings,
            "link_samples": link_statuses,
            "robots_status": robots_status,
        }
        audit.save()

        for finding in findings:
            AuditFinding.objects.create(audit=audit, **finding)

        AuditMetric.objects.bulk_create(
            [
                AuditMetric(audit=audit, label="Response status", value=str(status)),
                AuditMetric(audit=audit, label="Response time (ms)", value=str(response_time)),
                AuditMetric(audit=audit, label="HTML bytes", value=str(len(body))),
                AuditMetric(audit=audit, label="Total links parsed", value=str(len(absolute_links))),
                AuditMetric(audit=audit, label="Images parsed", value=str(len(page.images))),
            ]
        )

    except Exception as exc:
        audit.status = AuditRun.STATUS_FAILED
        audit.summary = f"Audit failed: {exc}"
        audit.save()

    return audit


def run_multi_page_audit(website: Website, urls: Iterable[str], user=None) -> List[AuditRun]:
    audits = []
    for page_url in urls:
        try:
            audits.append(run_audit(website, page_url, user))
        except Exception:
            continue
    return audits


def generate_audit_pdf(audit: AuditRun) -> bytes:
    buffer = BytesIO()

    try:
        pdfmetrics.registerFont(TTFont("Roboto", "Roboto-Regular.ttf"))
        base_font = "Roboto"
    except Exception:
        base_font = "Helvetica"

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )

    styles = getSampleStyleSheet()
    styles["Normal"].fontName = base_font
    styles["Heading1"].fontName = base_font
    styles["Heading2"].fontName = base_font

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName=base_font,
        fontSize=22,
        textColor=colors.HexColor("#1d4ed8"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Heading2"],
        fontName=base_font,
        fontSize=14,
        textColor=colors.HexColor("#475569"),
        spaceAfter=14,
    )
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName=base_font,
        fontSize=16,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=18,
        spaceAfter=8,
    )
    summary_style = ParagraphStyle(
        "Summary",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#1e293b"),
    )

    def _header_footer(canvas, document):
        canvas.saveState()
        canvas.setFont(base_font, 9)
        canvas.setFillColor(colors.HexColor("#94a3b8"))
        canvas.drawString(document.leftMargin, document.height + document.topMargin - 0.4 * inch, "QA Insights")
        canvas.drawRightString(
            document.leftMargin + document.width,
            document.bottomMargin - 0.5 * inch,
            f"Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    story = []
    story.append(Paragraph("QA Insights Audit Report", title_style))
    story.append(
        Paragraph(
            audit.website.name or audit.website.url,
            subtitle_style,
        )
    )

    detail_data = [
        ["Website", audit.website.name or audit.website.url],
        ["URL", audit.url],
        ["Status", audit.status.title()],
        ["Score", str(audit.score)],
        ["Response Time", f"{audit.response_time_ms} ms"],
        ["Generated", audit.created_at.strftime("%Y-%m-%d %H:%M")],
    ]

    detail_table = Table(detail_data, colWidths=[1.7 * inch, doc.width - 1.7 * inch])
    detail_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eff6ff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
                ("FONTNAME", (0, 0), (-1, -1), base_font),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dbeafe")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#93c5fd")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(detail_table)
    story.append(Spacer(1, 18))

    story.append(Paragraph("Summary", section_style))
    story.append(Paragraph(audit.summary or "No summary available.", summary_style))

    findings = list(audit.findings.all())
    if findings:
        story.append(Paragraph("Findings", section_style))
        severity_palette = {
            AuditFinding.SEVERITY_LOW: colors.HexColor("#6366f1"),
            AuditFinding.SEVERITY_MEDIUM: colors.HexColor("#f97316"),
            AuditFinding.SEVERITY_HIGH: colors.HexColor("#ef4444"),
        }
        for finding in findings:
            badge_color = severity_palette.get(finding.severity, colors.HexColor("#0ea5e9"))
            finding_data = [
                [
                    Paragraph(
                        f"<b>{finding.category.title()}</b> – {finding.severity.title()}",
                        ParagraphStyle("Badge", parent=summary_style, textColor=colors.white),
                    ),
                    "",
                ],
                [
                    Paragraph("<b>Issue</b>", summary_style),
                    Paragraph(finding.title, summary_style),
                ],
                [
                    Paragraph("<b>Description</b>", summary_style),
                    Paragraph(finding.description, summary_style),
                ],
                [
                    Paragraph("<b>Recommendation</b>", summary_style),
                    Paragraph(finding.recommendation, summary_style),
                ],
            ]
            finding_table = Table(
                finding_data,
                colWidths=[1.6 * inch, doc.width - 1.6 * inch],
                style=TableStyle(
                    [
                        ("SPAN", (0, 0), (-1, 0)),
                        ("BACKGROUND", (0, 0), (-1, 0), badge_color),
                        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                        ("LINEBEFORE", (0, 0), (-1, -1), 0.4, colors.HexColor("#bfdbfe")),
                        ("LINEABOVE", (0, 0), (-1, -1), 0.4, colors.HexColor("#bfdbfe")),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#bfdbfe")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                ),
            )
            story.append(finding_table)
            story.append(Spacer(1, 12))

    metrics = list(audit.metrics.all())
    if metrics:
        story.append(Paragraph("Key Metrics", section_style))
        metrics_data = [["Metric", "Value"]]
        metrics_data.extend([[metric.label, metric.value] for metric in metrics])
        metrics_table = Table(metrics_data, colWidths=[2.2 * inch, doc.width - 2.2 * inch])
        metrics_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, -1), base_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5f5")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(metrics_table)

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    buffer.seek(0)
    return buffer.read()
