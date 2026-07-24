#!/usr/bin/env python3
"""
Poll a published Outlook .ics feed and flash the Octolamp (WLED) before meetings.

State machine per poll (highest precedence first):
  - meeting in progress, <= END_WARN_MINUTES remaining -> green solid ("wrap it up")
  - meeting in progress, more time remaining           -> red solid ("in a meeting")
  - meeting starts within IMMINENT_MINUTES             -> red solid
  - meeting starts within WARN_MINUTES                 -> amber with EFFECT_ALERT
  - otherwise                                          -> restore the pre-alert lamp state

The pre-alert state is snapshotted on the first transition INTO an alert window
and restored on the first transition OUT.

Setup:
  1) Store the .ics URL in Keychain:
       security add-generic-password -a "$USER" -s "octolamp-ics-url" -w
       (paste the URL when prompted, press Ctrl-D)
  2) Copy .env.example to .env and edit it (at minimum set WLED_HOST and
     SELF_EMAIL_HINTS). Anything left unset falls back to the defaults in
     this file.
  3) pip3 install --user requests icalendar recurring-ical-events tzdata
  4) Run:  python3 octolamp_meeting_alert.py
     Ctrl-C to stop.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError
from zoneinfo import ZoneInfo

try:
    import icalendar
    import recurring_ical_events
except ImportError:
    sys.stderr.write("Missing deps. Run: pip3 install --user icalendar recurring-ical-events tzdata\n")
    sys.exit(1)


def _load_dotenv(path: str) -> None:
    """Minimal .env loader (no dep). KEY=VALUE per line, # comments, optional
    surrounding quotes stripped. Existing environment wins so shell overrides work.
    """
    try:
        f = open(path)
    except FileNotFoundError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            os.environ.setdefault(k, v)


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    return int(v) if v else default


def _env_colour(key: str, default: list[int]) -> list[int]:
    v = os.environ.get(key)
    if not v:
        return default
    parts = [int(x.strip()) for x in v.split(",") if x.strip()]
    return parts if len(parts) == 3 else default


def _env_tuple(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    v = os.environ.get(key)
    if not v:
        return default
    out: list[str] = []
    for item in v.split(","):
        s = item.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            s = s[1:-1].strip()
        if s:
            out.append(s.lower())
    return tuple(out)


WLED_HOST = os.environ.get("WLED_HOST", "wled.local")   # override in .env with your device's mDNS hostname or IP
POLL_SECONDS = _env_int("POLL_SECONDS", 30)
WARN_MINUTES = _env_int("WARN_MINUTES", 5)              # coloured this many minutes before a meeting starts
IMMINENT_MINUTES = _env_int("IMMINENT_MINUTES", 1)      # BUSY_COLOUR solid this many minutes before a meeting starts
END_WARN_MINUTES = _env_int("END_WARN_MINUTES", 5)      # ENDING_COLOUR solid during the last N minutes of a meeting
ICS_LOOKAHEAD_MINUTES = _env_int("ICS_LOOKAHEAD_MINUTES", 60)   # how far ahead to scan for upcoming meetings
ICS_LOOKBACK_MINUTES = _env_int("ICS_LOOKBACK_MINUTES", 240)    # how far back to scan so long meetings already in progress are picked up

WARN_COLOUR = _env_colour("WARN_COLOUR", [255, 140, 0])     # amber default: pre-meeting warn (rendered with EFFECT_ALERT)
BUSY_COLOUR = _env_colour("BUSY_COLOUR", [255, 0, 0])       # red default:   imminent and in-meeting (solid)
ENDING_COLOUR = _env_colour("ENDING_COLOUR", [0, 200, 40])  # green default: last END_WARN_MINUTES of a meeting (solid)
EFFECT_SOLID = _env_int("EFFECT_SOLID", 0)
EFFECT_ALERT = _env_int("EFFECT_ALERT", 12)  # WLED "Fade" effect: cycles between col1 and col2 without dropping brightness

STATE_IDLE = "idle"
STATE_WARN = "warn"                # <=WARN_MINUTES before start: WARN_COLOUR with EFFECT_ALERT
STATE_IMMINENT = "imminent"        # <=IMMINENT_MINUTES before start: BUSY_COLOUR solid
STATE_IN_MEETING = "in_meeting"    # meeting in progress, >END_WARN_MINUTES left: BUSY_COLOUR solid
STATE_ENDING = "ending"            # meeting in progress, <=END_WARN_MINUTES left: ENDING_COLOUR solid

SKIP_STATUSES = {"CANCELLED", "TENTATIVE"}
SKIP_PARTSTATS = {"DECLINED"}

# Comma-separated substrings looked for inside ATTENDEE fields (both the mailto
# URI and the CN display-name param) to identify "you". Used only to skip
# meetings you declined. Set SELF_EMAIL_HINTS in your .env. Case-insensitive.
SELF_EMAIL_HINTS = _env_tuple("SELF_EMAIL_HINTS", ("yourhandle",))


def load_ics_url() -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-a", subprocess.check_output(["whoami"]).decode().strip(),
         "-s", "octolamp-ics-url", "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit("Couldn't read octolamp-ics-url from Keychain. "
                         "Run: security add-generic-password -a \"$USER\" -s \"octolamp-ics-url\" -w")
    # Strip whitespace AND stray control characters that can sneak in when pasting into `security -w`
    return "".join(c for c in result.stdout if c.isprintable()).strip()


def fetch_ics(url: str) -> bytes:
    # OWA published-calendar endpoint 400s on Python's urlopen for reasons that aren't
    # worth debugging (headers, redirects, TLS cipher order). curl works, so use curl.
    result = subprocess.run(
        ["curl", "-fsSL", "--max-time", "15", "-A", "curl/8.4.0", url],
        capture_output=True,
    )
    if result.returncode != 0:
        raise URLError(f"curl exited {result.returncode}: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def declined_by_self(component) -> bool:
    attendees = component.get("attendee", []) or []
    # icalendar returns a single vCalAddress (a str subclass) when the event has
    # exactly one ATTENDEE, and a list when it has multiple. Iterating the bare
    # vCalAddress walks its characters, so normalise to a list first.
    if isinstance(attendees, str):
        attendees = [attendees]
    for attendee in attendees:
        # An ATTENDEE is usually a vCalAddress whose str() gives the mailto URI,
        # with the display name hiding in the CN param. Check both so hints like
        # "billy.fagan" (matches the URI) and "billy fagan" (matches the CN) both work.
        try:
            addr = str(attendee).lower()
        except Exception:
            addr = ""
        try:
            cn = str(attendee.params.get("CN", "")).lower()
        except Exception:
            cn = ""
        haystack = f"{addr} {cn}"
        if not any(hint in haystack for hint in SELF_EMAIL_HINTS):
            continue
        try:
            partstat = str(attendee.params.get("PARTSTAT", "")).upper()
        except Exception:
            partstat = ""
        if partstat in SKIP_PARTSTATS:
            return True
    return False


def _as_utc(v: dt.datetime) -> dt.datetime:
    if v.tzinfo is None:
        return v.replace(tzinfo=dt.timezone.utc)
    return v.astimezone(dt.timezone.utc)


def relevant_meetings(ics_bytes: bytes, now_utc: dt.datetime) -> list[tuple[dt.datetime, dt.datetime]]:
    """Return (start_utc, end_utc) tuples for meetings that either overlap now
    or start within ICS_LOOKAHEAD_MINUTES, sorted by start time.

    Widens the scan backwards by ICS_LOOKBACK_MINUTES so long meetings that
    started before the lookahead window are still picked up while they're in
    progress. Skips all-day events, cancelled/tentative events, and events
    the user declined.
    """
    cal = icalendar.Calendar.from_ical(ics_bytes)
    window_start = now_utc - dt.timedelta(minutes=ICS_LOOKBACK_MINUTES)
    window_end = now_utc + dt.timedelta(minutes=ICS_LOOKAHEAD_MINUTES)
    events = recurring_ical_events.of(cal).between(window_start, window_end)

    out: list[tuple[dt.datetime, dt.datetime]] = []
    for ev in events:
        status = str(ev.get("status", "")).upper()
        if status in SKIP_STATUSES:
            continue
        if declined_by_self(ev):
            continue
        start = ev.get("dtstart").dt
        if isinstance(start, dt.date) and not isinstance(start, dt.datetime):
            continue  # skip all-day
        end_prop = ev.get("dtend")
        if end_prop is not None:
            end = end_prop.dt
            if isinstance(end, dt.date) and not isinstance(end, dt.datetime):
                continue
        else:
            dur = ev.get("duration")
            if dur is None:
                continue  # unknown end, can't decide "in meeting" without it
            end = start + dur.dt
        start = _as_utc(start)
        end = _as_utc(end)
        if end <= now_utc:
            continue  # already finished
        if start > window_end:
            continue  # too far in the future
        out.append((start, end))
    out.sort(key=lambda x: x[0])
    return out


def wled_get_state() -> dict | None:
    try:
        with urlopen(f"http://{WLED_HOST}/json/state", timeout=5) as r:
            return json.loads(r.read())
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None


def wled_set(payload: dict) -> bool:
    try:
        req = Request(
            f"http://{WLED_HOST}/json/state",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as r:
            r.read()
        return True
    except (URLError, TimeoutError):
        return False


def apply_alert(color: list[int], effect: int) -> None:
    """Apply the alert colour/effect to every existing segment.

    Reads current segments so we preserve the user's ring/cat zoning
    instead of collapsing everything into one segment.

    Colour 2 is a dimmed copy of colour 1, not black. Two-colour effects
    modulate between colours, and dropping to black makes LEDs behind
    thicker diffusers (like the cat body) go visibly dark. Bottoming out
    at "dim amber" keeps every LED visibly lit through the whole cycle.
    """
    dim = [max(1, c // 8) for c in color]
    current = wled_get_state()
    segs = (current or {}).get("seg") or []
    if not segs:
        payload_segs = [{"col": [color, dim, [0, 0, 0]], "fx": effect, "pal": 0, "sx": 128, "ix": 200}]
    else:
        payload_segs = []
        for s in segs:
            payload_segs.append({
                "id": s.get("id", 0),
                "col": [color, dim, [0, 0, 0]],
                "fx": effect,
                "pal": 0,
                "sx": 128,
                "ix": 200,
            })
    wled_set({"on": True, "bri": 200, "seg": payload_segs})


def restore_lamp_state(saved: dict | None) -> None:
    """Restore the lamp to whatever it was doing before the alert.

    /json/state returns state directly (no {"state": ...} wrapper), so if the
    snapshot has that wrapper we peel it in case a future WLED version changes.

    If a preset was active at snapshot time (ps > 0), reload it by posting just
    {"ps": N}. Posting the full state blob back doesn't work: it contains both
    the preset id AND the resolved segments the preset expanded to, and WLED
    ends up applying the raw seg payload on top of the preset load, freezing
    the animation mid-frame. Reloading the preset by id lets WLED replay it
    cleanly.

    Only fall back to posting the raw on/bri/seg fields when no preset was
    active (ps missing or -1). If we have nothing at all, turn the lamp off.
    """
    if not saved:
        wled_set({"on": False})
        return
    state = saved.get("state", saved) if isinstance(saved, dict) else saved
    ps = state.get("ps", -1)
    if isinstance(ps, int) and ps > 0:
        wled_set({"ps": ps})
        return
    payload = {k: state[k] for k in ("on", "bri", "seg") if k in state}
    if payload:
        wled_set(payload)
    else:
        wled_set({"on": False})


def desired_state(
    meetings: list[tuple[dt.datetime, dt.datetime]],
    now_utc: dt.datetime,
) -> tuple[str, dt.datetime | None]:
    """Return (state, marker_time). marker_time is the meeting end for in-progress
    states and the meeting start for pre-meeting states, so the caller can log
    something useful.
    """
    active = [(s, e) for s, e in meetings if s <= now_utc < e]
    if active:
        active.sort(key=lambda x: x[1])  # earliest ending first
        _, end = active[0]
        remaining = end - now_utc
        if remaining <= dt.timedelta(minutes=END_WARN_MINUTES):
            return STATE_ENDING, end
        return STATE_IN_MEETING, end
    upcoming = [(s, e) for s, e in meetings if s > now_utc]
    if not upcoming:
        return STATE_IDLE, None
    upcoming.sort(key=lambda x: x[0])
    start, _ = upcoming[0]
    delta = start - now_utc
    if delta <= dt.timedelta(minutes=IMMINENT_MINUTES):
        return STATE_IMMINENT, start
    if delta <= dt.timedelta(minutes=WARN_MINUTES):
        return STATE_WARN, start
    return STATE_IDLE, start


def main() -> None:
    ics_url = load_ics_url()
    print(f"octolamp-meeting-alert: polling every {POLL_SECONDS}s, host={WLED_HOST}", flush=True)

    current_state = STATE_IDLE
    saved_lamp_state: dict | None = None
    ics_cache: bytes | None = None
    ics_cache_at: dt.datetime | None = None
    tz_local = ZoneInfo("Europe/London")

    while True:
        try:
            now_utc = dt.datetime.now(dt.timezone.utc)
            # Cache ICS for 60s to be gentle on the feed
            if ics_cache is None or (now_utc - ics_cache_at).total_seconds() > 60:
                try:
                    ics_cache = fetch_ics(ics_url)
                    ics_cache_at = now_utc
                except URLError as e:
                    print(f"[{now_utc:%H:%M:%S}] ics fetch failed: {e}", flush=True)
                    time.sleep(POLL_SECONDS)
                    continue

            meetings = relevant_meetings(ics_cache, now_utc)
            new_state, marker = desired_state(meetings, now_utc)

            if new_state != current_state:
                marker_local = marker.astimezone(tz_local).strftime("%H:%M") if marker else "-"
                label = "ends" if new_state in (STATE_IN_MEETING, STATE_ENDING) else "next"
                print(f"[{now_utc.astimezone(tz_local):%H:%M:%S}] {current_state} -> {new_state} ({label} {marker_local})", flush=True)
                if current_state == STATE_IDLE and new_state != STATE_IDLE:
                    saved_lamp_state = wled_get_state()
                if new_state == STATE_WARN:
                    apply_alert(WARN_COLOUR, EFFECT_ALERT)
                elif new_state == STATE_IMMINENT or new_state == STATE_IN_MEETING:
                    apply_alert(BUSY_COLOUR, EFFECT_SOLID)
                elif new_state == STATE_ENDING:
                    apply_alert(ENDING_COLOUR, EFFECT_SOLID)
                elif new_state == STATE_IDLE:
                    restore_lamp_state(saved_lamp_state)
                    saved_lamp_state = None
                current_state = new_state
        except KeyboardInterrupt:
            print("bye")
            if saved_lamp_state:
                restore_lamp_state(saved_lamp_state)
            return
        except Exception as e:
            print(f"loop error: {e}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
