"""
test_notify.py
--------------
Tests the notifier WITHOUT doing a real LinkedIn fetch.

Modes:
    1. Unit tests  -- validates HTML/text output, config checking, escape logic.
       Run automatically, no credentials needed.

    2. Live send   -- fires a real email to your inbox using your SMTP credentials.
       Triggered by passing --send on the command line:
           python test_notify.py --send

       Requires SMTP_USER, SMTP_PASSWORD, and EMAIL_RECIPIENT to be set in
       your .env file (see .env.example).

Usage:
    python test_notify.py          # unit tests only (safe, no email sent)
    python test_notify.py --send   # unit tests + real email with fake listings
"""

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s -- %(message)s",
    stream=sys.stdout,
)

# Load .env if it exists (python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
    logging.getLogger(__name__).info("Loaded .env file.")
except ImportError:
    pass  # dotenv is optional here; env vars can be set directly in the shell

from notifier import (  # noqa: E402
    send_notification,
    _build_html_body,
    _build_text_body,
    _build_subject,
    _check_config,
    _esc,
)

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS_COUNT = 0
FAIL_COUNT = 0

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗  {msg}{RESET}")
def info(msg): print(f"  {CYAN}ℹ{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")

def check(condition: bool, label: str) -> bool:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        ok(label)
        PASS_COUNT += 1
    else:
        fail(label)
        FAIL_COUNT += 1
    return condition


# ---------------------------------------------------------------------------
# Fake listings (no network needed)
# ---------------------------------------------------------------------------

FAKE_LISTINGS = [
    {
        "job_id":       "9000000001",
        "title":        "Software Engineer Intern",
        "company":      "Acme Tech",
        "location":     "Colombo, Western Province, Sri Lanka",
        "posted_date":  "2026-08-10",
        "posted_label": "1 hour ago",
        "link":         "https://lk.linkedin.com/jobs/view/software-engineer-intern-at-acme-9000000001",
    },
    {
        "job_id":       "9000000002",
        "title":        "Engineering Intern — Backend",
        "company":      "Startup <Island> & Co.",  # intentional HTML special chars
        "location":     "Remote, Sri Lanka",
        "posted_date":  "2026-08-09",
        "posted_label": "2 days ago",
        "link":         "https://lk.linkedin.com/jobs/view/engineering-intern-backend-9000000002",
    },
    {
        "job_id":       "9000000003",
        "title":        "Junior Full-Stack Developer",
        "company":      "LSEG",
        "location":     "",           # missing location — edge case
        "posted_date":  "",           # missing date — edge case
        "posted_label": "",
        "link":         "https://lk.linkedin.com/jobs/view/junior-full-stack-developer-9000000003",
    },
]

SINGLE_LISTING = [FAKE_LISTINGS[0]]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_subject_line():
    print(f"\n{BOLD}-- test_subject_line --{RESET}")
    s1 = _build_subject(1)
    s3 = _build_subject(3)
    check("1 new listing"   in s1, f"Singular: {s1!r}")
    check("3 new listings"  in s3, f"Plural:   {s3!r}")
    check("Sri Lanka" in s1,        "Contains location")
    check("🇱🇰" in s1,              "Contains flag emoji")


def test_html_escaping():
    print(f"\n{BOLD}-- test_html_escaping --{RESET}")
    check(_esc("a & b")     == "a &amp; b",    "& → &amp;")
    check(_esc("<script>")  == "&lt;script&gt;","< > escaped")
    check(_esc('"quoted"')  == "&quot;quoted&quot;", '" escaped')
    check(_esc("plain text") == "plain text",  "Plain text unchanged")


def test_html_body_structure():
    print(f"\n{BOLD}-- test_html_body_structure (3 listings) --{RESET}")
    html = _build_html_body(FAKE_LISTINGS)

    check("<!DOCTYPE html>" in html,            "Starts with DOCTYPE")
    check("<title>" in html,                    "Has <title> tag")
    check("New Job Listings" in html,           "Title text present")
    check("Sri Lanka" in html,                  "Location in header")
    check("3 New Listings Found" in html,       "Correct count in header")

    # Each listing's title should appear in the output
    for listing in FAKE_LISTINGS:
        title_esc = _esc(listing["title"])
        check(title_esc in html, f"Title found: {listing['title']!r}")

    # Links should be present
    for listing in FAKE_LISTINGS:
        check(listing["link"] in html, f"Link found for job_id={listing['job_id']}")

    # HTML special chars in company name should be escaped
    check("Startup &lt;Island&gt; &amp; Co." in html,
          "HTML special chars escaped in company name")


def test_html_body_single():
    print(f"\n{BOLD}-- test_html_body_structure (1 listing) --{RESET}")
    html = _build_html_body(SINGLE_LISTING)
    check("1 New Listing Found" in html, "Singular count in header")


def test_html_missing_fields():
    print(f"\n{BOLD}-- test_html_body (missing location/date) --{RESET}")
    html = _build_html_body([FAKE_LISTINGS[2]])  # listing with empty location/date
    # Should not crash, and should still have the title and link
    check(FAKE_LISTINGS[2]["title"] in html,   "Title renders with missing fields")
    check(FAKE_LISTINGS[2]["link"]  in html,   "Link renders with missing fields")
    check("View Job" in html,                  "CTA button present")


def test_text_body():
    print(f"\n{BOLD}-- test_text_body --{RESET}")
    text = _build_text_body(FAKE_LISTINGS)

    check("LinkedIn Job Tracker" in text,   "Header present")
    check("Sri Lanka" in text,              "Location present")

    for i, listing in enumerate(FAKE_LISTINGS, 1):
        check(listing["title"]   in text,   f"#{i} title in text body")
        check(listing["company"] in text,   f"#{i} company in text body")
        check(listing["link"]    in text,   f"#{i} link in text body")


def test_send_notification_empty():
    print(f"\n{BOLD}-- test_send_notification (empty list) --{RESET}")
    # Should return True immediately without attempting SMTP
    result = send_notification([])
    check(result is True, "send_notification([]) returns True (no-op)")


def test_check_config_missing():
    print(f"\n{BOLD}-- test_check_config (missing creds) --{RESET}")
    import config as cfg
    # Temporarily blank out credentials
    orig_user, orig_pass, orig_rcpt = cfg.SMTP_USER, cfg.SMTP_PASSWORD, cfg.EMAIL_RECIPIENT
    cfg.SMTP_USER = ""
    cfg.SMTP_PASSWORD = ""
    cfg.EMAIL_RECIPIENT = ""

    missing = _check_config()
    check("SMTP_USER"       in missing, "SMTP_USER detected as missing")
    check("SMTP_PASSWORD"   in missing, "SMTP_PASSWORD detected as missing")
    check("EMAIL_RECIPIENT" in missing, "EMAIL_RECIPIENT detected as missing")

    # send_notification should return False gracefully (not crash)
    result = send_notification(FAKE_LISTINGS)
    check(result is False, "send_notification returns False when config missing")

    # Restore
    cfg.SMTP_USER, cfg.SMTP_PASSWORD, cfg.EMAIL_RECIPIENT = orig_user, orig_pass, orig_rcpt


# ---------------------------------------------------------------------------
# Live send (opt-in via --send flag)
# ---------------------------------------------------------------------------

def test_live_send():
    print(f"\n{BOLD}-- LIVE SEND TEST --{RESET}")

    import config as cfg
    missing = _check_config()
    if missing:
        warn(f"Skipping live send — missing env vars: {', '.join(missing)}")
        warn("Set SMTP_USER, SMTP_PASSWORD, EMAIL_RECIPIENT in .env and re-run.")
        return

    info(f"Sending test email to {cfg.EMAIL_RECIPIENT} …")
    info(f"Using SMTP: {cfg.SMTP_HOST}:{cfg.SMTP_PORT} as {cfg.SMTP_USER}")
    info("Fake listings used — no real LinkedIn fetch.")

    success = send_notification(FAKE_LISTINGS)

    if success:
        ok(f"Email delivered! Check your inbox at {cfg.EMAIL_RECIPIENT}")
    else:
        fail("Email failed — check the logs above for details.")


# ---------------------------------------------------------------------------
# HTML preview dump
# ---------------------------------------------------------------------------

def dump_html_preview():
    """Write the rendered HTML to a file so you can open it in a browser."""
    out_path = os.path.join(os.path.dirname(__file__), "email_preview.html")
    html = _build_html_body(FAKE_LISTINGS)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    info(f"HTML preview saved → {out_path}")
    info("Open it in a browser to see how the email will look.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    live_send = "--send" in sys.argv

    print(f"\n{BOLD}{'='*65}")
    print("  LinkedIn Job Tracker -- Phase 4 Test Suite (notifier.py)")
    if live_send:
        print(f"  Mode: UNIT TESTS + LIVE EMAIL SEND")
    else:
        print(f"  Mode: UNIT TESTS ONLY  (use --send to also fire a real email)")
    print(f"{'='*65}{RESET}")

    # Unit tests (always run, no credentials needed)
    test_subject_line()
    test_html_escaping()
    test_html_body_structure()
    test_html_body_single()
    test_html_missing_fields()
    test_text_body()
    test_send_notification_empty()
    test_check_config_missing()

    # Generate HTML preview
    dump_html_preview()

    # Optional live send
    if live_send:
        test_live_send()

    print(f"\n{BOLD}{'='*65}")
    total = PASS_COUNT + FAIL_COUNT
    if FAIL_COUNT == 0:
        print(f"{GREEN}  All {total} checks passed! ✓{RESET}")
    else:
        print(f"{RED}  {PASS_COUNT}/{total} checks passed — {FAIL_COUNT} failed.{RESET}")
    print(f"{'='*65}{RESET}\n")

    sys.exit(0 if FAIL_COUNT == 0 else 1)
