"""Shared helpers for the test suite. Not a pytest conftest, just a regular module."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

# Make the top-level module importable when tests are run from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_ics(events: list[dict]) -> bytes:
    """Build a minimal valid VCALENDAR string from event dicts.

    Each event dict supports keys:
      uid, dtstart (datetime, UTC), dtend (datetime, UTC),
      summary, status, attendees (list of raw ATTENDEE lines minus "ATTENDEE:"),
      all_day (bool, uses date-only DTSTART/DTEND)
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//octolamp-tests//octolamp-tests//EN",
    ]
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev.get('uid', 'test@x')}")
        lines.append("DTSTAMP:20260101T000000Z")
        if ev.get("all_day"):
            lines.append(f"DTSTART;VALUE=DATE:{ev['dtstart'].strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{ev['dtend'].strftime('%Y%m%d')}")
        else:
            lines.append(f"DTSTART:{ev['dtstart'].strftime('%Y%m%dT%H%M%SZ')}")
            lines.append(f"DTEND:{ev['dtend'].strftime('%Y%m%dT%H%M%SZ')}")
        lines.append(f"SUMMARY:{ev.get('summary', 'Test')}")
        if "status" in ev:
            lines.append(f"STATUS:{ev['status']}")
        for a in ev.get("attendees", []):
            lines.append(f"ATTENDEE{a}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode()


def utc(y, mo, d, h=0, mi=0, s=0) -> dt.datetime:
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=dt.timezone.utc)
