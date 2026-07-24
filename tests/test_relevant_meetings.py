"""Tests for relevant_meetings(): the ICS parser wrapper."""
import datetime as dt
import unittest

from tests._helpers import ROOT, build_ics, utc  # noqa: F401
import octolamp_meeting_alert as m


class RelevantMeetingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = utc(2026, 1, 1, 12, 0, 0)
        self._saved_hints = m.SELF_EMAIL_HINTS
        m.SELF_EMAIL_HINTS = ("billy.fagan",)
        self.addCleanup(lambda: setattr(m, "SELF_EMAIL_HINTS", self._saved_hints))

    def test_returns_upcoming_meeting_in_window(self) -> None:
        ics = build_ics([{
            "dtstart": utc(2026, 1, 1, 12, 30),
            "dtend": utc(2026, 1, 1, 13, 0),
        }])
        out = m.relevant_meetings(ics, self.now)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], utc(2026, 1, 1, 12, 30))
        self.assertEqual(out[0][1], utc(2026, 1, 1, 13, 0))

    def test_returns_meeting_already_in_progress(self) -> None:
        ics = build_ics([{
            "dtstart": utc(2026, 1, 1, 11, 0),
            "dtend": utc(2026, 1, 1, 13, 0),
        }])
        out = m.relevant_meetings(ics, self.now)
        self.assertEqual(len(out), 1)

    def test_skips_already_finished_meeting(self) -> None:
        ics = build_ics([{
            "dtstart": utc(2026, 1, 1, 10, 0),
            "dtend": utc(2026, 1, 1, 11, 0),
        }])
        self.assertEqual(m.relevant_meetings(ics, self.now), [])

    def test_skips_far_future_meeting(self) -> None:
        far_start = self.now + dt.timedelta(minutes=m.ICS_LOOKAHEAD_MINUTES + 30)
        ics = build_ics([{
            "dtstart": far_start,
            "dtend": far_start + dt.timedelta(minutes=30),
        }])
        self.assertEqual(m.relevant_meetings(ics, self.now), [])

    def test_skips_all_day_events(self) -> None:
        ics = build_ics([{
            "dtstart": dt.date(2026, 1, 1),
            "dtend": dt.date(2026, 1, 2),
            "all_day": True,
        }])
        self.assertEqual(m.relevant_meetings(ics, self.now), [])

    def test_skips_cancelled(self) -> None:
        ics = build_ics([{
            "dtstart": utc(2026, 1, 1, 12, 30),
            "dtend": utc(2026, 1, 1, 13, 0),
            "status": "CANCELLED",
        }])
        self.assertEqual(m.relevant_meetings(ics, self.now), [])

    def test_skips_tentative(self) -> None:
        ics = build_ics([{
            "dtstart": utc(2026, 1, 1, 12, 30),
            "dtend": utc(2026, 1, 1, 13, 0),
            "status": "TENTATIVE",
        }])
        self.assertEqual(m.relevant_meetings(ics, self.now), [])

    def test_skips_declined_meeting(self) -> None:
        ics = build_ics([{
            "dtstart": utc(2026, 1, 1, 12, 30),
            "dtend": utc(2026, 1, 1, 13, 0),
            "attendees": [";PARTSTAT=DECLINED:mailto:billy.fagan@example.com"],
        }])
        self.assertEqual(m.relevant_meetings(ics, self.now), [])

    def test_results_sorted_by_start(self) -> None:
        ics = build_ics([
            {"uid": "b", "dtstart": utc(2026, 1, 1, 12, 40), "dtend": utc(2026, 1, 1, 13, 0)},
            {"uid": "a", "dtstart": utc(2026, 1, 1, 12, 10), "dtend": utc(2026, 1, 1, 12, 30)},
        ])
        out = m.relevant_meetings(ics, self.now)
        starts = [s for s, _ in out]
        self.assertEqual(starts, sorted(starts))


if __name__ == "__main__":
    unittest.main()
