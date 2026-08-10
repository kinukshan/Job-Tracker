"""
test_fetch.py
-------------
Quick verification script for fetcher.py.

Run this directly to confirm the fetcher is working correctly:
    python test_fetch.py

What it does:
    1. Calls fetch_listings() to hit LinkedIn's live guest API.
    2. Pretty-prints the raw results so you can visually verify each field.
    3. Runs a set of sanity checks on every returned listing.
    4. Tests edge-case handling using synthetic / malformed HTML cards.

No external services are mocked — this hits the real LinkedIn endpoint once.
Keep it under ~50 listings (controlled by config.MAX_LISTINGS) to be polite.
"""

import json
import logging
import sys

# ---------------------------------------------------------------------------
# Set up logging so we can see fetcher's internal messages while testing
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-8s %(name)s — %(message)s",
    stream=sys.stdout,
)

# Silence noisy third-party loggers
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)

from fetcher import _parse_listings, _extract_job_id, _strip_tracking, fetch_listings  # noqa: E402


# ---------------------------------------------------------------------------
# ANSI colour helpers (no dependencies)
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):  print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗  {msg}{RESET}")
def info(msg): print(f"  {CYAN}ℹ{RESET}  {msg}")


# ---------------------------------------------------------------------------
# Edge-case unit tests (no network)
# ---------------------------------------------------------------------------

def test_extract_job_id():
    """_extract_job_id correctly pulls the ID from various URL forms."""
    print(f"\n{BOLD}── Unit tests: _extract_job_id ──{RESET}")
    cases = [
        ("https://lk.linkedin.com/jobs/view/software-engineers-intern-at-codrizon-4448968893?position=1", "4448968893"),
        ("https://www.linkedin.com/jobs/view/4448968893",  "4448968893"),
        ("https://lk.linkedin.com/jobs/view/title-12345",  "12345"),
        ("https://example.com/no-id-here",                 ""),
        ("",                                               ""),
    ]
    all_passed = True
    for url, expected in cases:
        result = _extract_job_id(url)
        if result == expected:
            ok(f"job_id={result!r:20s}  ← {url[:60]}")
        else:
            fail(f"Expected {expected!r}, got {result!r} for {url}")
            all_passed = False
    return all_passed


def test_strip_tracking():
    """_strip_tracking removes query params from URLs."""
    print(f"\n{BOLD}── Unit tests: _strip_tracking ──{RESET}")
    cases = [
        (
            "https://lk.linkedin.com/jobs/view/title-123?position=1&pageNum=0&refId=xxx",
            "https://lk.linkedin.com/jobs/view/title-123",
        ),
        ("https://lk.linkedin.com/jobs/view/title-123", "https://lk.linkedin.com/jobs/view/title-123"),
        ("", ""),
    ]
    all_passed = True
    for raw, expected in cases:
        result = _strip_tracking(raw)
        if result == expected:
            ok(f"stripped={result!r}")
        else:
            fail(f"Expected {expected!r}, got {result!r}")
            all_passed = False
    return all_passed


def test_parse_malformed_html():
    """_parse_listings gracefully handles missing / malformed fields."""
    print(f"\n{BOLD}── Unit tests: _parse_listings (malformed HTML) ──{RESET}")

    cases = {
        "Empty HTML": ("", []),
        "No <li> at all": ("<div>nothing here</div>", []),
        "Li without link": ("<li><h3 class='base-search-card__title'>Title</h3></li>", []),
        "Missing title": (
            """<li>
                 <a class="base-card__full-link" href="https://lk.linkedin.com/jobs/view/missing-title-11111"></a>
               </li>""",
            [],  # should skip — title is empty
        ),
        "Valid minimal card": (
            """<li>
                 <a class="base-card__full-link"
                    href="https://lk.linkedin.com/jobs/view/engineer-intern-99999"></a>
                 <h3 class="base-search-card__title">Engineer Intern</h3>
               </li>""",
            1,  # should produce 1 listing
        ),
        "Valid card with all fields": (
            """<li>
                 <a class="base-card__full-link"
                    href="https://lk.linkedin.com/jobs/view/swe-intern-at-acme-12345678?position=1"></a>
                 <h3 class="base-search-card__title">SWE Intern</h3>
                 <h4 class="base-search-card__subtitle">
                   <a class="hidden-nested-link">Acme Corp</a>
                 </h4>
                 <span class="job-search-card__location">Colombo, Sri Lanka</span>
                 <time class="job-search-card__listdate" datetime="2026-08-05">5 days ago</time>
               </li>""",
            1,
        ),
    }

    all_passed = True
    for name, (html, expected) in cases.items():
        result = _parse_listings(html)
        count  = len(result)
        exp    = expected if isinstance(expected, int) else len(expected)

        if count == exp:
            ok(f"{name!r} → {count} listing(s) as expected")
        else:
            fail(f"{name!r} → expected {exp}, got {count}")
            all_passed = False

    return all_passed


# ---------------------------------------------------------------------------
# Live fetch test
# ---------------------------------------------------------------------------

def test_live_fetch():
    """
    Hit the real LinkedIn guest API and verify the structure of returned dicts.
    Expected fields and their types are checked for every listing.
    """
    print(f"\n{BOLD}── Live fetch test ──{RESET}")
    info("Calling fetch_listings() against live LinkedIn API …")

    listings = fetch_listings()

    if not listings:
        print(f"  {YELLOW}⚠  No listings returned. LinkedIn may be rate-limiting or "
              f"there are genuinely no results. Try again in a few minutes.{RESET}")
        return True  # Not a hard failure — depends on external service

    info(f"Received {len(listings)} listing(s). Checking structure …\n")

    required_fields = {
        "job_id":       str,
        "title":        str,
        "company":      str,
        "location":     str,
        "posted_date":  str,
        "posted_label": str,
        "link":         str,
    }

    all_passed = True
    for idx, listing in enumerate(listings, start=1):
        errors = []

        # Check all required keys exist and have correct type
        for field, ftype in required_fields.items():
            if field not in listing:
                errors.append(f"missing key '{field}'")
            elif not isinstance(listing[field], ftype):
                errors.append(f"'{field}' should be {ftype.__name__}, got {type(listing[field]).__name__}")

        # job_id must be non-empty and numeric
        if listing.get("job_id") and not listing["job_id"].isdigit():
            errors.append(f"job_id={listing['job_id']!r} is not all-digits")

        # link should start with https://
        if listing.get("link") and not listing["link"].startswith("https://"):
            errors.append(f"link doesn't start with https://: {listing['link']!r}")

        # posted_date, if present, should look like YYYY-MM-DD
        pd = listing.get("posted_date", "")
        if pd and len(pd) != 10:
            errors.append(f"posted_date format unexpected: {pd!r}")

        if errors:
            fail(f"Listing #{idx} ({listing.get('title', '?')!r}): {'; '.join(errors)}")
            all_passed = False
        else:
            ok(f"#{idx:02d}  {listing['title'][:40]:<40}  {listing['company'][:25]:<25}  {listing['posted_label']}")

    return all_passed


# ---------------------------------------------------------------------------
# Pretty-print results
# ---------------------------------------------------------------------------

def print_results(listings: list[dict]) -> None:
    """Print a formatted summary of all fetched listings."""
    if not listings:
        return

    print(f"\n{BOLD}{'─'*70}")
    print(f"  FETCHED LISTINGS (pretty-print)  — {len(listings)} total")
    print(f"{'─'*70}{RESET}\n")

    for i, listing in enumerate(listings, 1):
        print(f"{BOLD}{i:2d}. {listing['title']}{RESET}")
        print(f"    🏢  {listing['company']}")
        print(f"    📍  {listing['location']}")
        print(f"    🕒  {listing['posted_label']} ({listing['posted_date']})")
        print(f"    🔗  {listing['link']}")
        print(f"    🆔  job_id={listing['job_id']}")
        print()

    print(f"\n{BOLD}Full JSON output:{RESET}")
    print(json.dumps(listings, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n{BOLD}{'='*70}")
    print("  LinkedIn Job Listing Tracker — Phase 2 Test Suite")
    print(f"{'='*70}{RESET}")

    results = []

    # Unit tests (no network)
    results.append(test_extract_job_id())
    results.append(test_strip_tracking())
    results.append(test_parse_malformed_html())

    # Live fetch
    listings = []
    try:
        live_ok = test_live_fetch()
        results.append(live_ok)
        # Re-fetch (already fetched inside test_live_fetch) — reuse from globals
        from fetcher import fetch_listings as _fl
        listings = _fl() if live_ok else []
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)

    print_results(listings)

    # Summary
    passed = sum(results)
    total  = len(results)
    print(f"\n{BOLD}{'='*70}")
    if passed == total:
        print(f"{GREEN}  All {total} test groups passed! ✓{RESET}")
    else:
        print(f"{RED}  {passed}/{total} test groups passed.{RESET}")
    print(f"{'='*70}{RESET}\n")

    sys.exit(0 if passed == total else 1)
