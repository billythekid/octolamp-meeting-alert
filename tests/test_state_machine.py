"""Tests for the state machine: desired_state()."""
import datetime as dt
import unittest

from tests._helpers import ROOT, utc  # noqa: F401
import octolamp_meeting_alert as m


def _meeting(start: dt.datetime, mins: int) -> tuple[dt.datetime, dt.datetime]:
    return (start, start + dt.timedelta(minutes=mins))


class DesiredStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = utc(2026, 1, 1, 12, 0, 0)

    def test_no_meetings_is_idle(self) -> None:
        state, marker = m.desired_state([], self.now)
        self.assertEqual(state, m.STATE_IDLE)
        self.assertIsNone(marker)

    def test_far_future_meeting_is_idle_with_marker(self) -> None:
        start = self.now + dt.timedelta(minutes=30)
        state, marker = m.desired_state([_meeting(start, 30)], self.now)
        self.assertEqual(state, m.STATE_IDLE)
        self.assertEqual(marker, start)

    def test_within_warn_window_is_warn(self) -> None:
        start = self.now + dt.timedelta(minutes=m.WARN_MINUTES)
        state, marker = m.desired_state([_meeting(start, 30)], self.now)
        self.assertEqual(state, m.STATE_WARN)
        self.assertEqual(marker, start)

    def test_within_imminent_window_is_imminent(self) -> None:
        start = self.now + dt.timedelta(seconds=30)
        state, marker = m.desired_state([_meeting(start, 30)], self.now)
        self.assertEqual(state, m.STATE_IMMINENT)
        self.assertEqual(marker, start)

    def test_active_meeting_with_time_left_is_in_meeting(self) -> None:
        start = self.now - dt.timedelta(minutes=10)
        state, marker = m.desired_state([_meeting(start, 30)], self.now)
        self.assertEqual(state, m.STATE_IN_MEETING)
        self.assertEqual(marker, start + dt.timedelta(minutes=30))

    def test_active_meeting_in_last_window_is_ending(self) -> None:
        # 3 minutes remaining; END_WARN_MINUTES defaults to 5.
        start = self.now - dt.timedelta(minutes=27)
        state, marker = m.desired_state([_meeting(start, 30)], self.now)
        self.assertEqual(state, m.STATE_ENDING)
        self.assertEqual(marker, start + dt.timedelta(minutes=30))

    def test_ended_meeting_ignored(self) -> None:
        start = self.now - dt.timedelta(minutes=30)  # end == now
        state, _ = m.desired_state([_meeting(start, 30)], self.now)
        self.assertEqual(state, m.STATE_IDLE)

    def test_active_meeting_beats_upcoming_meeting(self) -> None:
        active_start = self.now - dt.timedelta(minutes=10)
        upcoming_start = self.now + dt.timedelta(minutes=2)
        state, marker = m.desired_state(
            [_meeting(active_start, 60), _meeting(upcoming_start, 30)], self.now,
        )
        self.assertEqual(state, m.STATE_IN_MEETING)
        self.assertEqual(marker, active_start + dt.timedelta(minutes=60))

    def test_earliest_ending_active_meeting_wins_for_marker(self) -> None:
        long_start = self.now - dt.timedelta(minutes=30)   # ends in 30
        short_start = self.now - dt.timedelta(minutes=25)  # ends in 5 -> ENDING
        state, marker = m.desired_state(
            [_meeting(long_start, 60), _meeting(short_start, 30)], self.now,
        )
        self.assertEqual(state, m.STATE_ENDING)
        self.assertEqual(marker, short_start + dt.timedelta(minutes=30))

    def test_soonest_upcoming_wins(self) -> None:
        near = self.now + dt.timedelta(minutes=3)
        far = self.now + dt.timedelta(minutes=45)
        state, marker = m.desired_state([_meeting(far, 30), _meeting(near, 30)], self.now)
        self.assertEqual(state, m.STATE_WARN)
        self.assertEqual(marker, near)


if __name__ == "__main__":
    unittest.main()
