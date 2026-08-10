"""
test_store.py
-------------
Tests for store.py — SQLite persistence and diff logic.

Run with:
    python test_store.py

Uses an ISOLATED in-memory / temp database so your real listings.db
is never touched. Every test starts with a clean state.
"""

import logging
import os
import sys
import tempfile

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-8s %(name)s -- %(message)s",
    stream=sys.stdout,
)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ---- Redirect DB to a temp file so we never touch the real database -------
import config as _cfg

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_cfg.DB_PATH = _tmp_db.name
_tmp_db.close()
# ---------------------------------------------------------------------------

import store  # noqa: E402  (import after patching config)

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
GREEN = "\033[92m"
RED   = "\033[91m"
CYAN  = "\033[96m"
BOLD  = "\033[1m"
RESET = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗  {msg}{RESET}")
def info(msg): print(f"  {CYAN}ℹ{RESET}  {msg}")

PASS_COUNT = 0
FAIL_COUNT = 0

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
# Sample fixtures
# ---------------------------------------------------------------------------

def _make_listing(job_id: str, title: str = "SWE Intern", company: str = "Acme") -> dict:
    """Create a minimal listing dict with the given job_id."""
    return {
        "job_id":       job_id,
        "title":        title,
        "company":      company,
        "location":     "Colombo, Sri Lanka",
        "posted_date":  "2026-08-10",
        "posted_label": "1 hour ago",
        "link":         f"https://lk.linkedin.com/jobs/view/{title.replace(' ', '-').lower()}-{job_id}",
    }

SAMPLE_LISTINGS = [
    _make_listing("1000000001", "Software Engineers - Intern",  "Codrizon"),
    _make_listing("1000000002", "Engineering Intern - SWE",     "LSEG"),
    _make_listing("1000000003", "Full-Stack Developer Intern",  "BLAZEVEX"),
]


# ---------------------------------------------------------------------------
# Helper: fresh DB before each test group
# ---------------------------------------------------------------------------

def reset_db():
    """Wipe and re-initialise the test database."""
    store.clear_all_listings()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_init_db():
    print(f"\n{BOLD}-- test_init_db --{RESET}")
    store.init_db()  # Should not raise
    count = store.get_listing_count()
    check(count == 0, "DB initialised with 0 rows")


def test_save_and_count():
    print(f"\n{BOLD}-- test_save_and_count --{RESET}")
    reset_db()

    inserted = store.save_listings(SAMPLE_LISTINGS)
    check(inserted == 3, f"save_listings returned {inserted} (expected 3)")

    count = store.get_listing_count()
    check(count == 3, f"get_listing_count()={count} (expected 3)")


def test_no_duplicates_on_resave():
    print(f"\n{BOLD}-- test_no_duplicates_on_resave --{RESET}")
    reset_db()

    store.save_listings(SAMPLE_LISTINGS)
    # Save the exact same batch again — INSERT OR IGNORE should swallow them
    inserted2 = store.save_listings(SAMPLE_LISTINGS)
    check(inserted2 == 0, f"Re-saving same listings inserted {inserted2} (expected 0)")

    count = store.get_listing_count()
    check(count == 3, f"Row count still 3 after duplicate save (got {count})")


def test_find_new_listings_all_new():
    print(f"\n{BOLD}-- test_find_new_listings (all new) --{RESET}")
    reset_db()  # DB is empty

    new = store.find_new_listings(SAMPLE_LISTINGS)
    check(len(new) == 3, f"find_new_listings returned {len(new)} (expected 3 — all new)")


def test_find_new_listings_none_new():
    print(f"\n{BOLD}-- test_find_new_listings (none new) --{RESET}")
    reset_db()
    store.save_listings(SAMPLE_LISTINGS)  # seed DB

    new = store.find_new_listings(SAMPLE_LISTINGS)
    check(len(new) == 0, f"find_new_listings returned {len(new)} (expected 0 — all known)")


def test_find_new_listings_partial():
    print(f"\n{BOLD}-- test_find_new_listings (partial) --{RESET}")
    reset_db()
    store.save_listings(SAMPLE_LISTINGS[:2])  # save first 2

    # Fetch all 3 — only the 3rd should be new
    new = store.find_new_listings(SAMPLE_LISTINGS)
    check(len(new) == 1, f"find_new_listings returned {len(new)} (expected 1)")
    if new:
        check(new[0]["job_id"] == "1000000003",
              f"New listing job_id={new[0]['job_id']} (expected '1000000003')")


def test_find_new_listings_empty_input():
    print(f"\n{BOLD}-- test_find_new_listings (empty input) --{RESET}")
    reset_db()

    new = store.find_new_listings([])
    check(new == [], f"Empty input returns [] (got {new!r})")


def test_get_all_listings():
    print(f"\n{BOLD}-- test_get_all_listings --{RESET}")
    reset_db()
    store.save_listings(SAMPLE_LISTINGS)

    rows = store.get_all_listings(limit=10)
    check(len(rows) == 3, f"get_all_listings returned {len(rows)} rows (expected 3)")

    # Verify each row has all expected keys including first_seen_at
    required_keys = {"job_id", "title", "company", "location",
                     "posted_date", "posted_label", "link", "first_seen_at"}
    for row in rows:
        missing = required_keys - set(row.keys())
        check(not missing, f"Row {row['job_id']} has all keys (missing: {missing})")


def test_get_all_listings_limit():
    print(f"\n{BOLD}-- test_get_all_listings (limit) --{RESET}")
    reset_db()
    store.save_listings(SAMPLE_LISTINGS)

    rows = store.get_all_listings(limit=2)
    check(len(rows) == 2, f"limit=2 returns {len(rows)} rows (expected 2)")


def test_save_empty_list():
    print(f"\n{BOLD}-- test_save_listings (empty list) --{RESET}")
    reset_db()

    inserted = store.save_listings([])
    check(inserted == 0, f"save_listings([]) returned {inserted} (expected 0)")
    check(store.get_listing_count() == 0, "DB still empty after saving empty list")


def test_ordering_preserved():
    """find_new_listings must preserve the order of the input list."""
    print(f"\n{BOLD}-- test_ordering_preserved --{RESET}")
    reset_db()

    new = store.find_new_listings(SAMPLE_LISTINGS)
    ids_out = [l["job_id"] for l in new]
    ids_in  = [l["job_id"] for l in SAMPLE_LISTINGS]
    check(ids_out == ids_in, f"Order preserved: {ids_out}")


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n{BOLD}{'='*65}")
    print("  LinkedIn Job Tracker -- Phase 3 Test Suite (store.py)")
    print(f"{'='*65}{RESET}")
    info(f"Using temp database: {_cfg.DB_PATH}")

    store.init_db()  # Create schema once

    test_init_db()
    test_save_and_count()
    test_no_duplicates_on_resave()
    test_find_new_listings_all_new()
    test_find_new_listings_none_new()
    test_find_new_listings_partial()
    test_find_new_listings_empty_input()
    test_get_all_listings()
    test_get_all_listings_limit()
    test_save_empty_list()
    test_ordering_preserved()

    # Cleanup temp file
    try:
        os.unlink(_cfg.DB_PATH)
    except OSError:
        pass

    print(f"\n{BOLD}{'='*65}")
    total = PASS_COUNT + FAIL_COUNT
    if FAIL_COUNT == 0:
        print(f"{GREEN}  All {total} checks passed! ✓{RESET}")
    else:
        print(f"{RED}  {PASS_COUNT}/{total} checks passed — {FAIL_COUNT} failed.{RESET}")
    print(f"{'='*65}{RESET}\n")

    sys.exit(0 if FAIL_COUNT == 0 else 1)
