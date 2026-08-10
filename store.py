"""
store.py
--------
Handles all SQLite persistence for the LinkedIn Job Listing Tracker.

Responsibilities:
    • Create and migrate the database schema on first run.
    • Save (upsert) a batch of listings, avoiding duplicates.
    • Diff a fresh batch against the database and return only NEW listings.
    • Provide helpers for querying stored listings (useful for debugging).

The database lives at the path defined by config.DB_PATH and is created
automatically (including its parent directory) if it doesn't exist yet.

Usage:
    from store import init_db, find_new_listings, save_listings

    init_db()                             # call once at startup
    new = find_new_listings(listings)     # diff fresh fetch vs DB
    save_listings(new)                    # persist the new ones
"""

import os
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, List

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

# The single table that stores every listing we've ever seen.
# job_id is the primary key — LinkedIn's own numeric ID guarantees uniqueness.
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS listings (
    job_id        TEXT PRIMARY KEY,   -- LinkedIn's numeric job ID
    title         TEXT NOT NULL,      -- Job title
    company       TEXT NOT NULL,      -- Company name
    location      TEXT,               -- Location string
    posted_date   TEXT,               -- ISO-8601 date (YYYY-MM-DD) or empty
    posted_label  TEXT,               -- Human label ("3 days ago") or empty
    link          TEXT NOT NULL,      -- Canonical job URL
    first_seen_at TEXT NOT NULL       -- ISO-8601 UTC datetime when we first saved this
);
"""

# Index on first_seen_at to make recency queries fast
_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_listings_first_seen
    ON listings (first_seen_at DESC);
"""


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Ensure the database file and schema exist.

    Creates the parent directory, the SQLite file, and the listings table
    if any of them don't already exist. Safe to call on every startup --
    uses CREATE IF NOT EXISTS throughout.
    """
    db_dir = os.path.dirname(config.DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        logger.debug("Database directory ready: %s", db_dir)

    with _get_connection() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        conn.commit()

    logger.info("Database initialised at: %s", config.DB_PATH)


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------

def find_new_listings(listings: List[dict]) -> List[dict]:
    """
    Compare a fresh list of listings against the database and return only
    those that have never been seen before (i.e. whose job_id is not in DB).

    This is the primary "diff" function. Call it after every fetch, then
    pass its result to save_listings() and the notifier.

    Args:
        listings: Full list of listing dicts from fetcher.fetch_listings().

    Returns:
        A (possibly empty) list of listing dicts that are genuinely new.
        Preserves the original ordering.
    """
    if not listings:
        logger.debug("find_new_listings: received empty list -- nothing to diff.")
        return []

    # Pull all known job_ids in a single query -- fast regardless of table size
    known_ids = _fetch_all_job_ids()

    new_listings = [l for l in listings if l["job_id"] not in known_ids]

    logger.info(
        "Diff complete: %d fetched, %d already known, %d new",
        len(listings),
        len(listings) - len(new_listings),
        len(new_listings),
    )
    return new_listings


def save_listings(listings: List[dict]) -> int:
    """
    Persist a batch of listings to the database.

    Uses INSERT OR IGNORE so that re-running the script never produces
    duplicates, even if the same listing appears in two consecutive fetches.

    Args:
        listings: List of listing dicts to insert (typically the output of
                  find_new_listings()).

    Returns:
        The number of rows actually inserted (ignored rows don't count).
    """
    if not listings:
        logger.debug("save_listings: nothing to save.")
        return 0

    now = _utc_now()
    rows = [
        (
            l["job_id"],
            l["title"],
            l["company"],
            l.get("location", ""),
            l.get("posted_date", ""),
            l.get("posted_label", ""),
            l["link"],
            now,
        )
        for l in listings
    ]

    with _get_connection() as conn:
        cursor = conn.executemany(
            """
            INSERT OR IGNORE INTO listings
                (job_id, title, company, location, posted_date, posted_label, link, first_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        inserted = cursor.rowcount

    logger.info("Saved %d new listing(s) to the database.", inserted)
    return inserted


# ---------------------------------------------------------------------------
# Query helpers (useful for debugging / manual inspection)
# ---------------------------------------------------------------------------

def get_all_listings(limit: int = 100) -> List[dict]:
    """
    Return the most recently seen listings from the database.

    Args:
        limit: Maximum number of rows to return (default 100).

    Returns:
        List of listing dicts ordered by first_seen_at DESC.
    """
    with _get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT job_id, title, company, location, posted_date,
                   posted_label, link, first_seen_at
            FROM listings
            ORDER BY first_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_listing_count() -> int:
    """Return the total number of listings stored in the database."""
    with _get_connection() as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM listings").fetchone()
    return count


def clear_all_listings() -> None:
    """
    Delete every row from the listings table.

    WARNING: Destructive -- use only in tests or to force a full re-notification.
    """
    with _get_connection() as conn:
        conn.execute("DELETE FROM listings")
        conn.commit()
    logger.warning("All listings cleared from the database.")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

@contextmanager
def _get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that opens a SQLite connection, yields it, and closes
    it cleanly even if an exception is raised.

    Row factory is set to sqlite3.Row so columns are accessible by name.
    """
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    # WAL mode for better concurrency (safe for single-writer use case too)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    except sqlite3.Error as exc:
        logger.error("Database error: %s", exc)
        conn.rollback()
        raise
    finally:
        conn.close()


def _fetch_all_job_ids() -> set:
    """
    Return a set of all job_id strings currently stored in the database.
    Using a set makes membership checks O(1).
    """
    with _get_connection() as conn:
        cursor = conn.execute("SELECT job_id FROM listings")
        return {row[0] for row in cursor.fetchall()}


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain Python dict."""
    return {
        "job_id":        row["job_id"],
        "title":         row["title"],
        "company":       row["company"],
        "location":      row["location"],
        "posted_date":   row["posted_date"],
        "posted_label":  row["posted_label"],
        "link":          row["link"],
        "first_seen_at": row["first_seen_at"],
    }


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string (e.g. '2026-08-10T11:05:00')."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
