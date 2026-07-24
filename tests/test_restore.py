"""Tests for restore_lamp_state(). Mocks wled_set to capture the payload."""
import unittest

from tests._helpers import ROOT  # noqa: F401
import octolamp_meeting_alert as m


class RestoreLampStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[dict] = []
        self._saved = m.wled_set
        m.wled_set = lambda payload: (self.calls.append(payload), True)[1]
        self.addCleanup(lambda: setattr(m, "wled_set", self._saved))

    def test_none_snapshot_turns_off(self) -> None:
        m.restore_lamp_state(None)
        self.assertEqual(self.calls, [{"on": False}])

    def test_empty_dict_turns_off(self) -> None:
        m.restore_lamp_state({})
        self.assertEqual(self.calls, [{"on": False}])

    def test_ps_positive_reloads_preset_only(self) -> None:
        snapshot = {"ps": 3, "bri": 128, "on": True, "seg": [{"fx": 115}]}
        m.restore_lamp_state(snapshot)
        self.assertEqual(self.calls, [{"ps": 3}])

    def test_ps_negative_falls_back_to_raw_state(self) -> None:
        snapshot = {"ps": -1, "bri": 128, "on": True, "seg": [{"fx": 0}]}
        m.restore_lamp_state(snapshot)
        self.assertEqual(self.calls, [{"bri": 128, "on": True, "seg": [{"fx": 0}]}])

    def test_missing_ps_falls_back_to_raw_state(self) -> None:
        snapshot = {"bri": 200, "on": True, "seg": [{"fx": 12}]}
        m.restore_lamp_state(snapshot)
        self.assertEqual(self.calls, [{"bri": 200, "on": True, "seg": [{"fx": 12}]}])

    def test_wrapped_state_shape_is_unwrapped(self) -> None:
        # Guard for future WLED versions that wrap state in {"state": ...}.
        snapshot = {"state": {"ps": 5}}
        m.restore_lamp_state(snapshot)
        self.assertEqual(self.calls, [{"ps": 5}])

    def test_ps_zero_treated_as_no_preset(self) -> None:
        snapshot = {"ps": 0, "on": True, "bri": 64}
        m.restore_lamp_state(snapshot)
        self.assertEqual(self.calls, [{"on": True, "bri": 64}])

    def test_no_useful_fields_turns_off(self) -> None:
        snapshot = {"ps": -1, "transition": 7}
        m.restore_lamp_state(snapshot)
        self.assertEqual(self.calls, [{"on": False}])


if __name__ == "__main__":
    unittest.main()
