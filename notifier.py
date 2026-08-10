"""
notifier.py
-----------
Sends a formatted HTML email (with plain-text fallback) whenever new
LinkedIn job listings are found.

Transport: Gmail SMTP via TLS (port 587) using a Gmail App Password.
Credentials are read from environment variables — never hardcoded.

Public API:
    send_notification(listings)  -- call with a list of new listing dicts.
                                    Does nothing if the list is empty.

Environment variables required (set in .env or GitHub Secrets):
    SMTP_USER        -- your Gmail address, e.g. you@gmail.com
    SMTP_PASSWORD    -- 16-char Gmail App Password (not your account password)
    EMAIL_RECIPIENT  -- destination address for alerts (can be same as SMTP_USER)

Optional overrides (defaults work fine for Gmail):
    SMTP_HOST        -- defaults to smtp.gmail.com
    SMTP_PORT        -- defaults to 587
"""

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_notification(listings: List[dict]) -> bool:
    """
    Send a formatted email alert for a batch of new job listings.

    Skips silently if the list is empty (no point sending an empty email).
    Returns True on success, False on any error (errors are logged but
    never re-raised — a notification failure must not crash the main run).

    Args:
        listings: List of NEW listing dicts (from store.find_new_listings).

    Returns:
        True if the email was delivered successfully, False otherwise.
    """
    if not listings:
        logger.debug("send_notification: no listings — skipping email.")
        return True

    # Validate config before trying to connect
    missing = _check_config()
    if missing:
        logger.error(
            "Cannot send email — missing environment variables: %s. "
            "Set them in your .env file or GitHub Secrets.",
            ", ".join(missing),
        )
        return False

    count   = len(listings)
    subject = _build_subject(count)
    html    = _build_html_body(listings)
    text    = _build_text_body(listings)

    return _send_email(subject, html, text)


# ---------------------------------------------------------------------------
# Email content builders
# ---------------------------------------------------------------------------

def _build_subject(count: int) -> str:
    """Build the email subject line."""
    noun = "listing" if count == 1 else "listings"
    return f"[Job Tracker] {count} new {noun} in Sri Lanka 🇱🇰"


def _build_html_body(listings: List[dict]) -> str:
    """
    Build a clean, inbox-safe HTML email body using inline CSS only
    (external stylesheets are stripped by most email clients).

    Args:
        listings: List of listing dicts to render.

    Returns:
        Full HTML string ready to send as the HTML part of a MIME email.
    """
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
    count   = len(listings)
    noun    = "listing" if count == 1 else "listings"

    # Build one card per listing
    cards_html = "\n".join(_render_card(l) for l in listings)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>New Job Listings</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,sans-serif;">

  <!-- Outer wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f4f6f9;padding:32px 0;">
    <tr><td align="center">

      <!-- Card container -->
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;
                    box-shadow:0 2px 12px rgba(0,0,0,0.08);
                    overflow:hidden;max-width:600px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#0a66c2 0%,#004182 100%);
                     padding:32px 36px;">
            <p style="margin:0;font-size:13px;color:#a8c8f0;
                      text-transform:uppercase;letter-spacing:1px;">
              LinkedIn Job Tracker
            </p>
            <h1 style="margin:8px 0 4px;font-size:24px;color:#ffffff;
                       font-weight:700;line-height:1.3;">
              {count} New {noun.title()} Found
            </h1>
            <p style="margin:0;font-size:13px;color:#a8c8f0;">
              Sri Lanka &nbsp;·&nbsp; {now_str}
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:28px 36px;">
            <p style="margin:0 0 20px;font-size:15px;color:#444;line-height:1.6;">
              Here are the latest software engineering opportunities we spotted
              on LinkedIn. Click any title to view the full posting.
            </p>

{cards_html}

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8f9fb;border-top:1px solid #e8eaed;
                     padding:20px 36px;">
            <p style="margin:0;font-size:12px;color:#999;line-height:1.6;">
              You're receiving this because you set up the LinkedIn Job Tracker.
              &nbsp;·&nbsp;
              Keywords: <strong>Software Engineer Intern</strong>
              &nbsp;·&nbsp;
              Location: <strong>Sri Lanka</strong>
              &nbsp;·&nbsp;
              Posted within: <strong>7 days</strong>
            </p>
          </td>
        </tr>

      </table>
      <!-- end card container -->

    </td></tr>
  </table>

</body>
</html>"""


def _render_card(listing: dict) -> str:
    """
    Render a single listing as an HTML card block (table-based for email
    client compatibility).

    Args:
        listing: A single listing dict.

    Returns:
        HTML string for the card.
    """
    title        = _esc(listing.get("title", "Untitled"))
    company      = _esc(listing.get("company", "Unknown Company"))
    location     = _esc(listing.get("location", ""))
    posted_label = _esc(listing.get("posted_label", ""))
    posted_date  = _esc(listing.get("posted_date", ""))
    link         = listing.get("link", "#")

    # Format meta line: location · posted label (date)
    meta_parts = []
    if location:
        meta_parts.append(f"📍 {location}")
    if posted_label:
        date_suffix = f" ({posted_date})" if posted_date else ""
        meta_parts.append(f"🕒 {posted_label}{date_suffix}")
    meta_line = "&nbsp;&nbsp;·&nbsp;&nbsp;".join(meta_parts)

    return f"""            <!-- Listing card -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="margin-bottom:16px;border:1px solid #e2e8f0;
                          border-radius:8px;overflow:hidden;">
              <tr>
                <td style="padding:18px 20px;">

                  <!-- Title -->
                  <a href="{link}"
                     style="text-decoration:none;color:#0a66c2;
                            font-size:17px;font-weight:700;line-height:1.3;
                            display:block;margin-bottom:4px;">
                    {title}
                  </a>

                  <!-- Company -->
                  <p style="margin:0 0 8px;font-size:14px;
                            color:#555;font-weight:600;">
                    🏢 {company}
                  </p>

                  <!-- Meta (location + date) -->
                  <p style="margin:0 0 14px;font-size:13px;color:#888;">
                    {meta_line}
                  </p>

                  <!-- CTA button -->
                  <a href="{link}"
                     style="display:inline-block;background:#0a66c2;
                            color:#ffffff;font-size:13px;font-weight:600;
                            padding:8px 18px;border-radius:6px;
                            text-decoration:none;">
                    View Job →
                  </a>

                </td>
              </tr>
            </table>"""


def _build_text_body(listings: List[dict]) -> str:
    """
    Build a plain-text fallback for email clients that don't render HTML.

    Args:
        listings: List of listing dicts.

    Returns:
        Plain-text string.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines   = [
        "LinkedIn Job Tracker — New Listings Alert",
        f"Generated: {now_str}",
        f"Location: Sri Lanka | Keywords: Software Engineer Intern",
        "=" * 60,
        "",
    ]

    for i, listing in enumerate(listings, 1):
        lines.append(f"{i}. {listing.get('title', 'Untitled')}")
        lines.append(f"   Company:  {listing.get('company', '')}")
        lines.append(f"   Location: {listing.get('location', '')}")
        lines.append(f"   Posted:   {listing.get('posted_label', '')} ({listing.get('posted_date', '')})")
        lines.append(f"   Link:     {listing.get('link', '')}")
        lines.append("")

    lines.append("=" * 60)
    lines.append("You're receiving this from your LinkedIn Job Tracker bot.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SMTP transport
# ---------------------------------------------------------------------------

def _send_email(subject: str, html_body: str, text_body: str) -> bool:
    """
    Connect to Gmail SMTP (TLS, port 587) and send a multipart/alternative
    email containing both a plain-text and an HTML part.

    Args:
        subject:   Email subject line.
        html_body: HTML version of the email body.
        text_body: Plain-text version of the email body.

    Returns:
        True on success, False on any SMTP or connection error.
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config.SMTP_USER
    msg["To"]      = config.EMAIL_RECIPIENT

    # Attach plain-text first (clients show the last matching part they support,
    # so HTML comes second and will be preferred by modern clients)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html",  "utf-8"))

    try:
        logger.info(
            "Connecting to %s:%d as %s …",
            config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER,
        )
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT,
                          timeout=30) as server:
            server.ehlo()
            server.starttls()          # upgrade to TLS
            server.ehlo()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(
                config.SMTP_USER,
                config.EMAIL_RECIPIENT,
                msg.as_string(),
            )

        logger.info(
            "Email sent successfully to %s (subject: %r)",
            config.EMAIL_RECIPIENT, subject,
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "SMTP authentication failed. Check SMTP_USER and SMTP_PASSWORD. "
            "Make sure you're using a Gmail App Password, not your account password."
        )
    except smtplib.SMTPRecipientsRefused as exc:
        logger.error("Recipient refused: %s", exc.recipients)
    except smtplib.SMTPException as exc:
        logger.error("SMTP error: %s", exc)
    except OSError as exc:
        logger.error("Connection error to %s:%d — %s",
                     config.SMTP_HOST, config.SMTP_PORT, exc)

    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_config() -> List[str]:
    """
    Check that all required environment variables are set.

    Returns:
        A list of missing variable names (empty list means all good).
    """
    required = {
        "SMTP_USER":       config.SMTP_USER,
        "SMTP_PASSWORD":   config.SMTP_PASSWORD,
        "EMAIL_RECIPIENT": config.EMAIL_RECIPIENT,
    }
    return [name for name, val in required.items() if not val]


def _esc(text: str) -> str:
    """Escape HTML special characters to prevent broken email rendering."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
