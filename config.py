"""
config.py
---------
Central configuration for the LinkedIn Job Listing Tracker.
All tunable parameters live here — edit this file to change keywords,
location, filters, or request behaviour without touching any other module.
"""

import os

# ---------------------------------------------------------------------------
# Search parameters
# ---------------------------------------------------------------------------

# Keywords to search for in LinkedIn's job search bar
SEARCH_KEYWORDS = "Software Engineer Intern"

# Geographic location string as LinkedIn understands it
SEARCH_LOCATION = "Sri Lanka"

# Time filter: number of seconds back from now.
#   r86400  = last 24 hours
#   r604800 = last 7 days  (default)
#   r2592000 = last 30 days
SEARCH_TIME_FILTER = "r604800"

# Job-type codes (comma-separated, URL-encoded elsewhere as needed)
#   F = Full-time
#   I = Internship
#   P = Part-time
#   C = Contract
SEARCH_JOB_TYPES = ["F", "I"]

# Maximum number of listings to fetch per run (LinkedIn returns 10 per page)
MAX_LISTINGS = 50

# ---------------------------------------------------------------------------
# LinkedIn guest API endpoint
# ---------------------------------------------------------------------------

LINKEDIN_GUEST_API = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)

# ---------------------------------------------------------------------------
# HTTP request settings
# ---------------------------------------------------------------------------

# Mimic a real browser so LinkedIn doesn't block us immediately
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Seconds to wait between paginated requests (be polite — don't hammer the site)
REQUEST_DELAY_SECONDS = 2.5

# Timeout for each HTTP request (seconds)
REQUEST_TIMEOUT_SECONDS = 15

# ---------------------------------------------------------------------------
# Retry / backoff settings
# ---------------------------------------------------------------------------

# Maximum number of attempts per page request (1 = no retry).
# On transient errors (timeout, connection reset, 5xx) the fetcher will
# sleep and retry up to this many times before giving up on that page.
MAX_RETRIES = 3

# Base delay in seconds for exponential backoff between retries.
#   Attempt 1 failed → wait BASE * 2^0 = 2s
#   Attempt 2 failed → wait BASE * 2^1 = 4s
#   Attempt 3 failed → wait BASE * 2^2 = 8s
RETRY_BACKOFF_BASE = 2.0

# Maximum backoff ceiling (seconds) — prevents extremely long waits.
RETRY_BACKOFF_MAX = 30.0

# How long to wait (seconds) after receiving HTTP 429 Too Many Requests.
# LinkedIn may impose this; we back off politely rather than hammering.
RATELIMIT_WAIT_SECONDS = 60.0

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# SQLite database file path (relative to project root)
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "listings.db")

# ---------------------------------------------------------------------------
# Email / SMTP notification (loaded from environment variables)
# ---------------------------------------------------------------------------

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")          # Your Gmail address
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # Gmail App Password
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")  # Where to send alerts

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "tracker.log")

# Rotating log settings — keeps logs from growing unbounded.
# Each file is capped at LOG_MAX_BYTES; up to LOG_BACKUP_COUNT old files
# are kept before the oldest is deleted.
LOG_MAX_BYTES    = 1 * 1024 * 1024   # 1 MB per file
LOG_BACKUP_COUNT = 5                  # keep tracker.log + 5 rotated backups
