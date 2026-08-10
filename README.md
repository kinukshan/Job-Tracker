# 🔍 LinkedIn Job Listing Tracker

A lightweight personal automation bot that monitors LinkedIn job postings
and emails you whenever a new one appears — so you never have to manually
refresh the page again.

Built as a portfolio project: clean, modular Python with SQLite persistence
and GitHub Actions scheduling. No paid APIs, no Selenium, no server required.

---

## 📋 Table of Contents

- [The Problem](#the-problem)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Quick Start (Local)](#quick-start-local)
- [Environment Variables](#environment-variables)
- [Usage Examples](#usage-examples)
- [GitHub Actions Setup](#github-actions-setup)
- [Configuration Reference](#configuration-reference)
- [Error Handling & Resilience](#error-handling--resilience)
- [Extending the Bot](#extending-the-bot)
- [Troubleshooting](#troubleshooting)

---

## The Problem

Job hunting is a waiting game. You either miss postings because you checked
too late, or you waste time refreshing the same page ten times a day.

This bot solves that by running every 30 minutes, comparing the latest
LinkedIn results against a local database of everything it has already seen,
and sending you an email only when something genuinely new shows up.

**Target configuration (easily changeable in `config.py`):**
- **Keywords:** `Software Engineer Intern`
- **Location:** `Sri Lanka`
- **Recency:** Posted within the last 7 days
- **Job types:** Internship + Full-time
- **Notification:** HTML email via Gmail SMTP

---

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│  Every 30 minutes (GitHub Actions cron)                     │
│                                                             │
│  1. fetch_listings()   ──▶  LinkedIn guest API (no login)   │
│        │                    Paginated HTML scraping          │
│        │                    Retry + backoff on failure       │
│        ▼                                                     │
│  2. find_new_listings() ──▶  SQLite diff                    │
│        │                    O(1) set lookup per listing      │
│        ▼                                                     │
│  3. send_notification() ──▶  Gmail SMTP                     │
│        │                    HTML + plain-text email          │
│        │                    Skips if nothing is new          │
│        ▼                                                     │
│  4. save_listings()    ──▶  SQLite (INSERT OR IGNORE)        │
│        │                    Committed back to repo            │
│        ▼                                                     │
│  5. git push data/listings.db  (state survives next run)    │
└─────────────────────────────────────────────────────────────┘
```

### Why the LinkedIn guest API?

LinkedIn's `/jobs-guest/jobs/api/seeMoreJobPostings/search` endpoint is
publicly accessible without login and returns paginated HTML fragments.
No Selenium, no Playwright, no headless browser — just `requests` +
`BeautifulSoup`. Each page is fetched with a polite 2.5-second delay.

### Why SQLite + commit-back?

GitHub Actions runners are ephemeral (wiped after every run). The simplest
persistence layer for a personal project is to commit the SQLite database
file back to the repo after each run with `git push`. The file is small
(a few KB even after months), and `[skip ci]` in the commit message
prevents an infinite trigger loop.

---

## Architecture

```
job-listing-tracker/
├── config.py       ← All tunables in one place (keywords, delays, retries…)
├── fetcher.py      ← Fetch + parse LinkedIn → list of dicts
├── store.py        ← SQLite init, save, diff (find_new_listings)
├── notifier.py     ← Gmail SMTP HTML email builder + sender
├── main.py         ← Orchestrator (fetch → diff → notify → save)
│
├── test_fetch.py   ← Unit tests + live fetch validation for fetcher.py
├── test_store.py   ← Isolated SQLite tests (uses temp DB, never touches real one)
├── test_notify.py  ← HTML/text rendering tests + optional --send live fire
│
├── data/
│   └── listings.db ← SQLite database (committed to repo for CI persistence)
├── logs/
│   └── tracker.log ← Rotating log (1 MB × 5 backups, gitignored locally)
│
├── .github/
│   └── workflows/
│       └── job_tracker.yml  ← Cron schedule + secrets injection + commit-back
│
├── .env.example    ← Template for local credentials
├── .gitignore
└── requirements.txt
```

**Module responsibilities (one concern each):**

| Module | Input | Output |
|---|---|---|
| `fetcher.py` | — | `list[dict]` of job listings |
| `store.py` | `list[dict]` | new listings / SQLite rows |
| `notifier.py` | `list[dict]` | email sent (bool) |
| `main.py` | CLI args | exit code (0/1) |

---

## Quick Start (Local)

### Prerequisites

- Python 3.9 or higher
- A Gmail account with **2FA enabled**
- A [Gmail App Password](https://myaccount.google.com/apppasswords) (16 chars)

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/job-listing-tracker.git
cd job-listing-tracker

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
SMTP_USER=yourname@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop   # 16-char App Password (spaces OK)
EMAIL_RECIPIENT=yourname@gmail.com
```

### 3. Verify the fetcher works

```bash
python3 test_fetch.py
```

Expected output: unit tests pass, then 20–50 live listings printed.

### 4. Run a dry run (no email, no DB write)

```bash
python3 main.py --dry-run --verbose
```

### 5. Send a test email with fake listings

```bash
python3 test_notify.py --send
```

Check your inbox — you should receive the formatted HTML email within seconds.

### 6. Run for real

```bash
python3 main.py
```

On first run every listing is "new" and you'll get one large email.
On subsequent runs only genuinely new postings trigger a notification.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SMTP_USER` | ✅ | — | Your Gmail address |
| `SMTP_PASSWORD` | ✅ | — | 16-char Gmail App Password |
| `EMAIL_RECIPIENT` | ✅ | — | Email address to send alerts to |
| `SMTP_HOST` | ❌ | `smtp.gmail.com` | SMTP server host |
| `SMTP_PORT` | ❌ | `587` | SMTP server port (TLS) |

> **Gmail App Password setup:**
> 1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
> 2. Select app → **Mail**, device → **Other** → name it "Job Tracker"
> 3. Copy the 16-character password shown (spaces are fine to include or omit)
> 4. Paste as `SMTP_PASSWORD` — this is **not** your Google account password

---

## Usage Examples

```bash
# Normal run — fetch, diff, email if new, save
python3 main.py

# Dry run — fetch and diff but skip email and DB write (safe to run any time)
python3 main.py --dry-run

# Force a notification email even if no new listings (useful for testing)
python3 main.py --force-notify

# Verbose — full DEBUG logging to console
python3 main.py --verbose

# Combine flags
python3 main.py --dry-run --verbose

# Run individual test suites
python3 test_fetch.py          # tests fetcher (hits live LinkedIn API once)
python3 test_store.py          # tests SQLite layer (isolated, no network)
python3 test_notify.py         # tests email rendering (no network, no SMTP)
python3 test_notify.py --send  # as above + fires a real email with fake data
```

---

## GitHub Actions Setup

### 1. Push the project to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/job-listing-tracker.git
git push -u origin main
```

### 2. Add GitHub Secrets

Navigate to your repo → **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret name | Value |
|---|---|
| `SMTP_USER` | your Gmail address |
| `SMTP_PASSWORD` | your 16-char App Password |
| `EMAIL_RECIPIENT` | destination email |

Optional secrets (leave empty to use defaults):

| Secret name | Value |
|---|---|
| `SMTP_HOST` | smtp.gmail.com |
| `SMTP_PORT` | 587 |

### 3. The workflow runs automatically

The workflow (`.github/workflows/job_tracker.yml`) triggers:
- **Every 30 minutes** via cron schedule
- **Manually** via the Actions tab → "Run workflow" button

On manual runs you can toggle **Dry run** and **Force notify** options
directly from the GitHub UI.

### 4. Check the logs

- **Live run output:** Actions tab → click any run → "Fetch, Diff & Notify" job
- **Detailed log file:** each run uploads `logs/tracker.log` as an artifact
  (retained 14 days) — download it from the run summary page

### How CI persistence works

```
┌──────────────── GitHub Actions Runner ────────────────────┐
│  git checkout   →  data/listings.db  already in repo      │
│  pip install                                               │
│  python main.py                                            │
│  git add data/listings.db                                  │
│  git commit "chore: update listings.db [skip ci]"         │
│  git push       →  state survives the next run            │
└───────────────────────────────────────────────────────────┘
```

The `[skip ci]` tag in the commit message tells GitHub Actions not to
trigger another workflow run from the DB commit itself.

---

## Configuration Reference

All tunables live in [`config.py`](config.py). Edit this file — no other
module needs to change.

### Search parameters

```python
SEARCH_KEYWORDS    = "Software Engineer Intern"  # LinkedIn search query
SEARCH_LOCATION    = "Sri Lanka"                 # Location filter
SEARCH_TIME_FILTER = "r604800"                   # r86400=24h, r604800=7d, r2592000=30d
SEARCH_JOB_TYPES   = ["F", "I"]                 # F=Full-time, I=Internship, P=Part-time
MAX_LISTINGS       = 50                          # Hard cap per run
```

### Request politeness

```python
REQUEST_DELAY_SECONDS   = 2.5   # Sleep between paginated requests
REQUEST_TIMEOUT_SECONDS = 15    # Per-request timeout
```

### Retry / backoff

```python
MAX_RETRIES             = 3     # Extra attempts after first failure
RETRY_BACKOFF_BASE      = 2.0   # Seconds (doubles each attempt: 2s, 4s, 8s)
RETRY_BACKOFF_MAX       = 30.0  # Ceiling on backoff wait
RATELIMIT_WAIT_SECONDS  = 60.0  # Wait on HTTP 429 (rate limit)
```

### Logging

```python
LOG_PATH         = "logs/tracker.log"
LOG_MAX_BYTES    = 1_048_576   # 1 MB per file before rotation
LOG_BACKUP_COUNT = 5           # tracker.log + 5 rotated backups
```

---

## Error Handling & Resilience

| Failure scenario | Behaviour |
|---|---|
| LinkedIn returns no results | Logged as WARNING, exits 0, retries next scheduled run |
| Network timeout | Retried up to `MAX_RETRIES` times with exponential backoff |
| HTTP 429 rate-limit | Waits `RATELIMIT_WAIT_SECONDS` (default 60s) then retries |
| HTTP 403 / 404 | Logged as ERROR, no retry, rest of pipeline continues |
| SMTP auth failure | Logged as ERROR with hint to check App Password, exits 0 |
| DB write failure | Logged as CRITICAL, exits 1 |
| Malformed HTML card | Skipped silently, rest of page parsed normally |

The bot follows the principle: **a notification failure must never prevent
the database from being saved**, so a missed email does not cause duplicate
alerts on the next run.

---

## Extending the Bot

### Change the notification channel

The `send_notification(listings)` interface in `notifier.py` is the only
integration point. Replace the email logic with:

- **Discord webhook:** `requests.post(webhook_url, json={"content": text})`
- **Telegram bot:** `requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", ...)`
- **Slack webhook:** `requests.post(webhook_url, json={"text": text})`

### Add keyword filtering

In `main.py`, after `find_new_listings()`:

```python
KEYWORDS = ["backend", "intern", "python"]
new_listings = [
    l for l in new_listings
    if any(k.lower() in l["title"].lower() for k in KEYWORDS)
]
```

### Change the schedule

Edit the cron expression in `.github/workflows/job_tracker.yml`:

```yaml
- cron: "*/30 * * * *"   # every 30 minutes (current)
- cron: "0 * * * *"      # every hour
- cron: "0 8,12,18 * * *"  # 3 times a day (8 AM, noon, 6 PM UTC)
```

### Watch multiple locations

Call `fetch_listings()` once per location and merge the results:

```python
# In config.py
SEARCH_LOCATIONS = ["Sri Lanka", "Remote"]

# In main.py
from fetcher import fetch_listings
import config
all_listings = []
for loc in config.SEARCH_LOCATIONS:
    config.SEARCH_LOCATION = loc
    all_listings.extend(fetch_listings())
```

---

## Troubleshooting

### "No listings returned" on every run

- LinkedIn may have changed their HTML structure. Run `python3 test_fetch.py`
  and check the raw output. Update the CSS selectors in `fetcher.py` if needed.
- You may be rate-limited. Increase `REQUEST_DELAY_SECONDS` in `config.py`.

### Email not arriving

1. Check your spam/junk folder.
2. Confirm `SMTP_PASSWORD` is a Gmail **App Password** (16 chars), not your
   account password.
3. Make sure 2FA is enabled on your Google account (required for App Passwords).
4. Run `python3 test_notify.py --send` locally and check the console output.

### GitHub Actions: "Authentication failure" on git push

Ensure the workflow has `permissions: contents: write` (already set).
If you use a protected branch, you may need a Personal Access Token (PAT)
instead of `GITHUB_TOKEN`.

### The database grows and is committed every run even with no new listings

This should not happen — the workflow only commits if `git diff --cached`
finds changes. If it does, check that WAL journal files (`*.db-shm`, `*.db-wal`)
are listed in `.gitignore`.

### Running on Python 3.9

The project targets Python 3.9+ (type hints use `Optional[X]` from `typing`
rather than `X | None`). All features are compatible with 3.9.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.9+ |
| HTTP client | `requests` |
| HTML parsing | `BeautifulSoup4` + `lxml` |
| Persistence | `SQLite3` (stdlib) |
| Email | `smtplib` (stdlib) |
| Scheduling | GitHub Actions cron |
| Secrets | GitHub Actions Secrets |

---

*Built with ❤️ as a personal productivity tool and portfolio project.*
