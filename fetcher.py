"""
fetcher.py
----------
Responsible for fetching raw job listings from LinkedIn's public guest API
and parsing them into clean Python dictionaries.

Each returned listing dict has these guaranteed keys:
    {
        "job_id"      : str   -- unique LinkedIn job ID (used for deduplication)
        "title"       : str   -- job title
        "company"     : str   -- company name
        "location"    : str   -- job location string
        "posted_date" : str   -- ISO-8601 date string (YYYY-MM-DD) or "" if missing
        "posted_label": str   -- human label ("3 days ago") or "" if missing
        "link"        : str   -- canonical job URL (cleaned of tracking params)
    }

Resilience:
    - Each page request is retried up to config.MAX_RETRIES times on transient
      errors (timeouts, connection resets, HTTP 5xx) using exponential backoff
      with random jitter.
    - HTTP 429 (rate-limited) triggers a long configurable wait before retrying.
    - All errors are logged; failures never propagate to callers.

Politeness:
    - config.REQUEST_DELAY_SECONDS pause between paginated requests.
    - Realistic browser User-Agent header.
    - Hard cap of config.MAX_LISTINGS total results.

Usage:
    from fetcher import fetch_listings
    listings = fetch_listings()
"""

import random
import re
import time
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_listings() -> list[dict]:
    """
    Fetch all matching job listings from LinkedIn and return them as a list
    of clean dictionaries.

    Paginates through results (10 per page) until MAX_LISTINGS is reached
    or there are no more results.

    Returns:
        A list of listing dicts (may be empty if nothing was found or if
        the request failed). Never raises — errors are logged and an empty
        list is returned so callers stay simple.
    """
    all_listings: list[dict] = []
    start = 0
    page = 1

    job_type_param = "%2C".join(config.SEARCH_JOB_TYPES)  # e.g. "F%2CI"

    logger.info(
        "Starting fetch | keywords=%r | location=%r | max=%d",
        config.SEARCH_KEYWORDS,
        config.SEARCH_LOCATION,
        config.MAX_LISTINGS,
    )

    while len(all_listings) < config.MAX_LISTINGS:
        params = {
            "keywords": config.SEARCH_KEYWORDS,
            "location": config.SEARCH_LOCATION,
            "f_TPR":    config.SEARCH_TIME_FILTER,
            "f_JT":     job_type_param,
            "start":    start,
        }

        logger.debug("Fetching page %d (start=%d) …", page, start)

        html = _fetch_page(params)
        if html is None:
            # _fetch_page already logged the error
            break

        page_listings = _parse_listings(html)

        if not page_listings:
            logger.debug("No listings on page %d — stopping pagination.", page)
            break

        all_listings.extend(page_listings)
        logger.info("Page %d: found %d listings (total so far: %d)",
                    page, len(page_listings), len(all_listings))

        start += 10
        page += 1

        # Polite delay between paginated requests
        if len(all_listings) < config.MAX_LISTINGS:
            logger.debug("Sleeping %.1fs before next page …", config.REQUEST_DELAY_SECONDS)
            time.sleep(config.REQUEST_DELAY_SECONDS)

    # Trim to the hard cap
    result = all_listings[:config.MAX_LISTINGS]
    logger.info("Fetch complete. Total listings returned: %d", len(result))
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _fetch_page(params: dict) -> Optional[str]:
    """
    Make a single HTTP GET to the LinkedIn guest API with automatic retry
    and exponential backoff on transient errors.

    Retry policy:
        - Retries on: Timeout, ConnectionError, HTTP 5xx
        - HTTP 429 (rate limit): waits config.RATELIMIT_WAIT_SECONDS, then retries
        - No retry on: HTTP 4xx (except 429), parse errors
        - Maximum attempts: 1 + config.MAX_RETRIES
        - Backoff: config.RETRY_BACKOFF_BASE * 2^attempt  (+/- 0-1s jitter)
        - Backoff ceiling: config.RETRY_BACKOFF_MAX

    Args:
        params: Query parameters dict (keywords, location, f_TPR, etc.)

    Returns:
        Raw HTML string on success, or None after all retries are exhausted.
    """
    max_attempts = 1 + config.MAX_RETRIES

    for attempt in range(max_attempts):
        try:
            response = requests.get(
                config.LINKEDIN_GUEST_API,
                params=params,
                headers=config.REQUEST_HEADERS,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )

            # ── Rate-limited: back off and retry ──────────────────────────
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 0))
                wait = max(retry_after, config.RATELIMIT_WAIT_SECONDS)
                logger.warning(
                    "HTTP 429 Too Many Requests — LinkedIn is rate-limiting us. "
                    "Waiting %.0fs before retry (attempt %d/%d) …",
                    wait, attempt + 1, max_attempts,
                )
                time.sleep(wait)
                continue   # don't count as a backoff attempt

            response.raise_for_status()   # raises HTTPError for other 4xx/5xx
            return response.text          # success

        except requests.exceptions.Timeout:
            logger.warning(
                "Request timed out after %ds (attempt %d/%d).",
                config.REQUEST_TIMEOUT_SECONDS, attempt + 1, max_attempts,
            )

        except requests.exceptions.ConnectionError as exc:
            logger.warning(
                "Connection error (attempt %d/%d): %s",
                attempt + 1, max_attempts, exc,
            )

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code
            if 400 <= status < 500:
                # Client errors (403, 404 …) — no point retrying
                logger.error(
                    "HTTP %d — not retrying (client error): %s", status, exc
                )
                return None
            # Server error (5xx) — retry
            logger.warning(
                "HTTP %d server error (attempt %d/%d): %s",
                status, attempt + 1, max_attempts, exc,
            )

        except requests.exceptions.RequestException as exc:
            logger.warning(
                "Unexpected request error (attempt %d/%d): %s",
                attempt + 1, max_attempts, exc,
            )

        # ── Exponential backoff before next attempt ────────────────────────
        if attempt < max_attempts - 1:
            # jitter: randomise between 0-1s to avoid thundering-herd retries
            jitter = random.uniform(0, 1)
            backoff = min(
                config.RETRY_BACKOFF_BASE * (2 ** attempt) + jitter,
                config.RETRY_BACKOFF_MAX,
            )
            logger.info(
                "Backing off %.1fs before retry %d/%d …",
                backoff, attempt + 2, max_attempts,
            )
            time.sleep(backoff)

    logger.error(
        "All %d attempt(s) failed for params=%s. Giving up on this page.",
        max_attempts, params,
    )
    return None


def _parse_listings(html: str) -> list[dict]:
    """
    Parse the raw HTML fragment returned by LinkedIn's guest API into a list
    of clean listing dicts.

    LinkedIn returns an HTML snippet of <li> elements — one per job card.
    We extract:
        • title       — from <h3 class="base-search-card__title">
        • company     — from <h4 class="base-search-card__subtitle"> > <a>
        • location    — from <span class="job-search-card__location">
        • link        — from <a class="base-card__full-link"> (stripped of tracking)
        • job_id      — extracted from the job URL path
        • posted_date — from <time datetime="YYYY-MM-DD"> attribute
        • posted_label— from <time> element text ("3 days ago")

    Missing fields are returned as empty strings (never None / KeyError).

    Args:
        html: Raw HTML string from the LinkedIn guest API.

    Returns:
        List of listing dicts; empty list if parsing yielded nothing.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("li")

    if not cards:
        logger.debug("_parse_listings: no <li> cards found in HTML.")
        return []

    listings = []

    for card in cards:
        try:
            listing = _parse_single_card(card)
            if listing:
                listings.append(listing)
        except Exception as exc:  # noqa: BLE001 — guard against unexpected card shapes
            logger.warning("Skipping malformed card: %s", exc)

    return listings


def _parse_single_card(card) -> Optional[dict]:
    """
    Parse one <li> job card and return a listing dict, or None if the card
    doesn't contain the minimum required fields (title + link).

    Args:
        card: A BeautifulSoup Tag representing a single <li> card.

    Returns:
        A listing dict, or None if the card is invalid.
    """
    # --- Link & Job ID ---
    link_tag = card.find("a", class_="base-card__full-link")
    if not link_tag:
        # Some cards are pagination/promo elements — skip them
        return None

    raw_link = link_tag.get("href", "").strip()
    clean_link = _strip_tracking(raw_link)
    job_id = _extract_job_id(clean_link)

    if not job_id:
        logger.debug("Could not extract job_id from link: %s", raw_link)
        return None

    # --- Title ---
    title_tag = card.find("h3", class_="base-search-card__title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # --- Company ---
    subtitle_tag = card.find("h4", class_="base-search-card__subtitle")
    if subtitle_tag:
        company_link = subtitle_tag.find("a")
        company = (
            company_link.get_text(strip=True)
            if company_link
            else subtitle_tag.get_text(strip=True)
        )
    else:
        company = ""

    # --- Location ---
    location_tag = card.find("span", class_="job-search-card__location")
    location = location_tag.get_text(strip=True) if location_tag else ""

    # --- Posted date ---
    time_tag = card.find("time")
    if time_tag:
        posted_date  = time_tag.get("datetime", "").strip()   # e.g. "2026-08-05"
        posted_label = time_tag.get_text(strip=True)           # e.g. "5 days ago"
    else:
        posted_date  = ""
        posted_label = ""

    if not title:
        logger.debug("Card with job_id=%s has no title — skipping.", job_id)
        return None

    return {
        "job_id":       job_id,
        "title":        title,
        "company":      company,
        "location":     location,
        "posted_date":  posted_date,
        "posted_label": posted_label,
        "link":         clean_link,
    }


def _extract_job_id(url: str) -> str:
    """
    Extract the numeric LinkedIn job ID from a job view URL.

    LinkedIn job URLs follow the pattern:
        https://*.linkedin.com/jobs/view/<slug>-<job_id>?...

    We grab the last numeric segment before any query string.

    Args:
        url: A LinkedIn job URL string.

    Returns:
        The job ID string (e.g. "4448968893"), or "" if not found.
    """
    # Match a sequence of digits at the end of the URL path
    match = re.search(r"-(\d+)(?:\?|$)", url)
    if match:
        return match.group(1)

    # Fallback: try /view/<digits>
    match = re.search(r"/view/(\d+)", url)
    if match:
        return match.group(1)

    return ""


def _strip_tracking(url: str) -> str:
    """
    Remove LinkedIn tracking query parameters from a job URL, keeping only
    the clean canonical form.

    Example:
        In:  https://lk.linkedin.com/jobs/view/title-at-co-12345?position=1&pageNum=0&refId=xxx
        Out: https://lk.linkedin.com/jobs/view/title-at-co-12345

    Args:
        url: A raw LinkedIn URL potentially containing tracking params.

    Returns:
        The URL stripped of everything after the "?" query separator.
    """
    return url.split("?")[0] if "?" in url else url
