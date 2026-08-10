"""
main.py
-------
Entry-point orchestrator for the LinkedIn Job Listing Tracker.

Pipeline on every run:
    1.  init_db()           — ensure schema exists
    2.  fetch_listings()    — hit LinkedIn guest API, return parsed dicts
    3.  find_new_listings() — diff against SQLite, return only unseen ones
    4.  send_notification() — email new listings (skips if list is empty)
    5.  save_listings()     — persist new listings so they won't re-trigger

Exit codes:
    0 — completed successfully (even if no new listings were found)
    1 — a critical error occurred (fetch failed entirely, DB error, etc.)

Usage:
    python main.py                  # normal run
    python main.py --dry-run        # fetch + diff but do NOT send email or save
    python main.py --force-notify   # send email even if no new listings (for testing)
"""

import argparse
import logging
import logging.handlers
import os
import sys
import time

# Load .env in local development (python-dotenv); no-op if not installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import config
from fetcher import fetch_listings
from notifier import send_notification
from store import find_new_listings, init_db, save_listings

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
# Logs go to BOTH the console and a rotating log file.
# The log file path is defined in config.LOG_PATH.

def _setup_logging(verbose: bool = False) -> None:
    """Configure root logger to write to stdout and a rotating log file.

    File logs rotate at config.LOG_MAX_BYTES and up to config.LOG_BACKUP_COUNT
    old files are kept, so the logs/ directory never grows unbounded.
    """
    log_dir = os.path.dirname(config.LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    level = logging.DEBUG if verbose else logging.INFO

    # Console handler — always at INFO+ so the GitHub Actions log is readable
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Rotating file handler — DEBUG always so the file has full detail
    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_PATH,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)

    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s -- %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[console_handler, file_handler],
    )

    # Quiet down noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("charset_normalizer").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LinkedIn Job Listing Tracker — fetch, diff, and notify.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                  Normal run (fetch → diff → email → save)
  python main.py --dry-run        Fetch and diff but skip email and DB write
  python main.py --force-notify   Send email even if no new listings found
  python main.py --verbose        Enable DEBUG-level logging
""",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and diff but do NOT send email or save to DB.",
    )
    parser.add_argument(
        "--force-notify",
        action="store_true",
        help="Send notification even when no new listings are found (uses last fetch).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, force_notify: bool = False) -> int:
    """
    Execute the full tracker pipeline.

    Args:
        dry_run:      If True, skip email and DB write (safe to call any time).
        force_notify: If True, send notification even when new list is empty.

    Returns:
        0 on success, 1 on critical failure.
    """
    start_time = time.monotonic()
    logger.info("=" * 60)
    logger.info("LinkedIn Job Tracker -- run started")
    logger.info("  Python   : %s", sys.version.split()[0])
    logger.info("  keywords : %s", config.SEARCH_KEYWORDS)
    logger.info("  location : %s", config.SEARCH_LOCATION)
    logger.info("  job types: %s", ", ".join(config.SEARCH_JOB_TYPES))
    logger.info("  max list : %d", config.MAX_LISTINGS)
    logger.info("  retries  : %d  (backoff base: %.1fs, max: %.1fs)",
                config.MAX_RETRIES, config.RETRY_BACKOFF_BASE, config.RETRY_BACKOFF_MAX)
    logger.info("  dry_run  : %s", dry_run)
    logger.info("  log file : %s", config.LOG_PATH)
    logger.info("=" * 60)


    # ── Step 1: Ensure DB schema ─────────────────────────────────────────
    try:
        init_db()
    except Exception as exc:
        logger.critical("Failed to initialise database: %s", exc)
        return 1

    # ── Step 2: Fetch listings from LinkedIn ─────────────────────────────
    logger.info("Step 1/4 — Fetching listings from LinkedIn …")
    listings = fetch_listings()

    if not listings:
        logger.warning(
            "No listings returned from LinkedIn. "
            "This may be a rate-limit, network issue, or a change in LinkedIn's HTML. "
            "Check the logs above for details."
        )
        _log_duration(start_time)
        return 0  # Not a hard failure — try again next run

    logger.info("Fetched %d listing(s) total.", len(listings))

    # ── Step 3: Diff against DB ───────────────────────────────────────────
    logger.info("Step 2/4 — Comparing against known listings …")
    new_listings = find_new_listings(listings)

    if new_listings:
        logger.info("Found %d NEW listing(s):", len(new_listings))
        for i, listing in enumerate(new_listings, 1):
            logger.info(
                "  %d. %s @ %s (%s)",
                i, listing["title"], listing["company"], listing["posted_label"],
            )
    else:
        logger.info("No new listings found this run.")

    # ── Step 4: Send notification ─────────────────────────────────────────
    to_notify = new_listings if not force_notify else listings
    if to_notify:
        logger.info("Step 3/4 — Sending email notification (%d listing(s)) …",
                    len(to_notify))
        if dry_run:
            logger.info("[DRY RUN] Skipping email send.")
        else:
            success = send_notification(to_notify)
            if not success:
                logger.error(
                    "Email delivery failed. Listings will still be saved "
                    "to avoid re-notifying on the next run."
                )
    else:
        logger.info("Step 3/4 — No notification needed (no new listings).")

    # ── Step 5: Persist new listings ─────────────────────────────────────
    if new_listings:
        logger.info("Step 4/4 — Saving %d new listing(s) to DB …",
                    len(new_listings))
        if dry_run:
            logger.info("[DRY RUN] Skipping DB write.")
        else:
            save_listings(new_listings)
    else:
        logger.info("Step 4/4 — Nothing to save.")

    _log_duration(start_time)
    logger.info("Run complete.")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_duration(start: float) -> None:
    elapsed = time.monotonic() - start
    logger.info("Total run time: %.1f seconds", elapsed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = _parse_args()
    _setup_logging(verbose=args.verbose)
    sys.exit(run(dry_run=args.dry_run, force_notify=args.force_notify))
