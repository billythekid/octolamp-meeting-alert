"""Tests for declined_by_self, including the single-vs-multi-attendee gotcha
that motivated adding this suite in the first place.
"""
import unittest

import icalendar

from tests._helpers import ROOT, build_ics, utc  # noqa: F401
import octolamp_meeting_alert as m


def _events(ics: bytes):
    return list(icalendar.Calendar.from_ical(ics).walk("VEVENT"))


class DeclinedBySelfTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_hints = m.SELF_EMAIL_HINTS
        self.addCleanup(lambda: setattr(m, "SELF_EMAIL_HINTS", self._saved_hints))

    def _ev(self, attendees: list[str]):
        ics = build_ics([{
            "dtstart": utc(2026, 1, 1, 10),
            "dtend": utc(2026, 1, 1, 11),
            "attendees": attendees,
        }])
        return _events(ics)[0]

    def test_single_attendee_declined_matches_uri(self) -> None:
        # Regression: single attendee used to iterate its characters.
        m.SELF_EMAIL_HINTS = ("billy.fagan",)
        ev = self._ev([";PARTSTAT=DECLINED:mailto:billy.fagan@example.com"])
        self.assertTrue(m.declined_by_self(ev))

    def test_single_attendee_declined_matches_cn(self) -> None:
        m.SELF_EMAIL_HINTS = ("billy fagan",)
        ev = self._ev([';CN="Billy Fagan";PARTSTAT=DECLINED:mailto:other@example.com'])
        self.assertTrue(m.declined_by_self(ev))

    def test_multiple_attendees_declined(self) -> None:
        m.SELF_EMAIL_HINTS = ("billy.fagan",)
        ev = self._ev([
            ";PARTSTAT=ACCEPTED:mailto:someone@example.com",
            ";PARTSTAT=DECLINED:mailto:billy.fagan@example.com",
        ])
        self.assertTrue(m.declined_by_self(ev))

    def test_accepted_is_not_declined(self) -> None:
        m.SELF_EMAIL_HINTS = ("billy.fagan",)
        ev = self._ev([";PARTSTAT=ACCEPTED:mailto:billy.fagan@example.com"])
        self.assertFalse(m.declined_by_self(ev))

    def test_hint_matches_only_other_attendee(self) -> None:
        m.SELF_EMAIL_HINTS = ("billy.fagan",)
        ev = self._ev([
            ";PARTSTAT=DECLINED:mailto:someone.else@example.com",
            ";PARTSTAT=ACCEPTED:mailto:billy.fagan@example.com",
        ])
        self.assertFalse(m.declined_by_self(ev))

    def test_case_insensitive_matching(self) -> None:
        m.SELF_EMAIL_HINTS = ("billy fagan",)
        ev = self._ev([';CN="BILLY FAGAN";PARTSTAT=DECLINED:mailto:x@example.com'])
        self.assertTrue(m.declined_by_self(ev))

    def test_no_attendees_returns_false(self) -> None:
        m.SELF_EMAIL_HINTS = ("billy.fagan",)
        ev = self._ev([])
        self.assertFalse(m.declined_by_self(ev))

    def test_empty_hints_never_matches(self) -> None:
        m.SELF_EMAIL_HINTS = ()
        ev = self._ev([";PARTSTAT=DECLINED:mailto:billy.fagan@example.com"])
        self.assertFalse(m.declined_by_self(ev))


if __name__ == "__main__":
    unittest.main()
