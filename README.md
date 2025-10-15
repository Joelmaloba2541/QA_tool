# QA Tool

> _Because every great digital experience deserves a quality check._

## ☕️ What is this?
`QA Tool` is a Django-powered web auditor that takes your URL, pokes around the HTML, and brings back a curated report covering availability, performance, SEO, accessibility, and structure. It is equal parts watchdog, critic, and cheerleader for your website.

## ✨ Features at a Glance
- **Interactive dashboard** — Point your browser at `http://localhost:8000/` and run ad-hoc audits from the form.
- **Smart findings** — Each audit produces prioritized findings with actionable recommendations.
- **Quick metrics** — Response time, payload size, HTTP status, and more packed into a tidy summary.
- **Link health sampling** — Sniffs out broken links by sampling the first few anchor tags it discovers.
- **Robots awareness** — Checks for `robots.txt` and nudges you when crawlers are left wandering.
- **Reusable data model** — `Website`, `AuditRun`, `AuditFinding`, and `AuditMetric` keep historical context so you can trend over time.

## 🗺️ Architecture
```
qa_tool/
├─ qa_tool/         # Django project settings & routing
└─ audit/           # App with models, services, UI dashboard, tests
   ├─ services.py   # Core auditing engine (link checks, parsing, scoring)
   ├─ models.py     # Persistence layer for websites, audits, findings, metrics
   ├─ views.py      # Dashboard endpoint for running audits
   └─ templates/    # `dashboard.html` UI
```

## 🚀 Quick Start
- **[Clone]** `git clone https://github.com/Joelmaloba2541/QA-tool.git`
- **[Install]** `pip install -r requirements.txt` (or add dependencies manually if using a virtual environment)
- **[Migrate]** `python manage.py migrate`
- **[Run dev server]** `python manage.py runserver`
- **[Visit]** Open `http://localhost:8000/` and either select a saved website or drop a fresh URL.

The dashboard will run `run_audit()` under the hood, surface the latest findings, and list your recent audit history.

## 🧪 Testing
- Run targeted tests: `python manage.py test audit`
- Expect coverage for the happy path and failure handling of `run_audit()`.

## 🔍 Behind the Scenes
- **HTML parsing** — `services._PageParser` uses Python's `HTMLParser` to catalog titles, meta tags, headings, forms, images, and links.
- **Scoring** — `services._calculate_score()` starts at 100 and deducts based on finding severity.
- **Findings** — `services._evaluate_findings()` inspects slow responses, missing meta descriptions, empty alt text, broken links, and more.
- **Persistence** — Data lands in SQLite by default; swap `DATABASES` in `qa_tool/settings.py` if you need something beefier.

## 🧭 Roadmap Ideas
- **Background jobs** for long-running or scheduled audits.
- **API endpoints** to trigger audits programmatically.
- **Export** to CSV or PDF via the existing data models.
- **Authentication** and role separation for team-wide usage.

## 💡 Tips
- Create a superuser (`python manage.py createsuperuser`) to browse everything via Django Admin.
- When a page is stubborn (timeouts, SSL issues), the dashboard will still show the failure details alongside the audit entry.
- Keep an eye on `audit/services.py`—that's where new heuristics or integrations belong.

---

Happy auditing! 🎯
