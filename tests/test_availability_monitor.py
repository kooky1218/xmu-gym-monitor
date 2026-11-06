from __future__ import annotations

import unittest

from src.monitor.availability_monitor import (
    AvailabilityMonitor,
    SlotAvailability,
)
from src.monitor.config import MonitorConfig


class UnusedReader:
    def read_gym_snapshot(self) -> dict:
        raise AssertionError("evaluate_snapshot must not read the network")


def make_snapshot(
    *,
    source: str = "network_live",
    date: str = "2026-11-06",
    time_range: str = "18:00-19:00",
    remaining: int | None = 3,
    is_open: bool | None = True,
) -> dict:
    return {
        "stadium_id": 16,
        "venue_id": 123,
        "fetched_at": "2026-11-05T20:00:00+08:00",
        "meta": {
            "data_source": source,
            "fetched_at": "2026-11-05T20:00:00+08:00",
        },
        "intervals": {
            "slots": [
                {
                    "date": date,
                    "time_range": time_range,
                    "interval_id": 77,
                    "column_id": 9,
                    "area_name": "健身房",
                    "personal_capacity": 95,
                    "selected": 92,
                    "remaining": remaining,
                    "is_open": is_open,
                }
            ]
        },
    }


class AvailabilityMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = MonitorConfig(
            target_dates=["2026-11-06"],
            target_slots=["18:00-19:00"],
            min_remaining=1,
            enabled=True,
        )
        self.monitor = AvailabilityMonitor(UnusedReader(), self.config)

    def test_matching_date_and_slot(self) -> None:
        result = self.monitor.evaluate_snapshot(make_snapshot())
        self.assertEqual(len(result.slots), 1)
        self.assertEqual(result.slots[0].date, "2026-11-06")
        self.assertEqual(result.slots[0].time_range, "18:00-19:00")
        self.assertEqual(result.slots[0].start_time, "18:00")
        self.assertEqual(result.slots[0].end_time, "19:00")
        self.assertEqual(result.slots[0].slot_id, "77:9")

    def test_non_matching_date_is_excluded(self) -> None:
        result = self.monitor.evaluate_snapshot(
            make_snapshot(date="2026-11-07")
        )
        self.assertEqual(result.slots, ())

    def test_non_matching_slot_is_excluded(self) -> None:
        result = self.monitor.evaluate_snapshot(
            make_snapshot(time_range="19:00-20:00")
        )
        self.assertEqual(result.slots, ())

    def test_zero_remaining_is_unavailable(self) -> None:
        result = self.monitor.evaluate_snapshot(make_snapshot(remaining=0))
        self.assertEqual(result.slots[0].state, SlotAvailability.UNAVAILABLE)
        self.assertFalse(result.slots[0].notification_eligible)

    def test_positive_remaining_is_available(self) -> None:
        result = self.monitor.evaluate_snapshot(make_snapshot(remaining=3))
        self.assertEqual(result.slots[0].state, SlotAvailability.AVAILABLE)
        self.assertTrue(result.slots[0].notification_eligible)

    def test_closed_slot_is_unavailable(self) -> None:
        result = self.monitor.evaluate_snapshot(
            make_snapshot(remaining=3, is_open=False)
        )
        self.assertEqual(result.slots[0].state, SlotAvailability.UNAVAILABLE)

    def test_unknown_remaining_is_unknown(self) -> None:
        result = self.monitor.evaluate_snapshot(make_snapshot(remaining=None))
        self.assertEqual(result.slots[0].state, SlotAvailability.UNKNOWN)
        self.assertFalse(result.slots[0].notification_eligible)

    def test_cache_source_never_notifies(self) -> None:
        result = self.monitor.evaluate_snapshot(make_snapshot(source="cache"))
        self.assertEqual(result.slots[0].state, SlotAvailability.AVAILABLE)
        self.assertFalse(result.slots[0].notification_eligible)
        self.assertTrue(result.test_mode)

    def test_mock_source_never_notifies(self) -> None:
        result = self.monitor.evaluate_snapshot(make_snapshot(source="mock"))
        self.assertEqual(result.slots[0].state, SlotAvailability.AVAILABLE)
        self.assertFalse(result.slots[0].notification_eligible)
        self.assertTrue(result.test_mode)

    def test_live_source_can_notify(self) -> None:
        result = self.monitor.evaluate_snapshot(
            make_snapshot(source="network_live")
        )
        self.assertTrue(result.slots[0].notification_eligible)
        self.assertFalse(result.test_mode)

    def test_miniprogram_live_source_can_notify(self) -> None:
        result = self.monitor.evaluate_snapshot(
            make_snapshot(source="mini_program_live")
        )
        self.assertTrue(result.slots[0].notification_eligible)
        self.assertFalse(result.test_mode)

    def test_date_entry_open_is_available_without_inventing_remaining(
        self,
    ) -> None:
        self.config.target_slots = []
        snapshot = make_snapshot(source="mini_program_live")
        raw = snapshot["intervals"]["slots"][0]
        raw.update(
            {
                "time_range": "日期可预约",
                "remaining": None,
                "selected": None,
                "personal_capacity": None,
                "availability_kind": "date_entry",
                "is_open": True,
            }
        )
        result = self.monitor.evaluate_snapshot(snapshot)
        self.assertEqual(len(result.slots), 1)
        self.assertEqual(result.slots[0].state, SlotAvailability.AVAILABLE)
        self.assertIsNone(result.slots[0].remaining)
        self.assertTrue(result.slots[0].notification_eligible)

    def test_minimum_remaining_threshold(self) -> None:
        self.config.min_remaining = 5
        result = self.monitor.evaluate_snapshot(make_snapshot(remaining=4))
        self.assertEqual(result.slots[0].state, SlotAvailability.UNAVAILABLE)

    def test_dynamic_options_come_from_snapshot(self) -> None:
        dates, slots = AvailabilityMonitor.discover_options(
            make_snapshot(date="2026-11-08", time_range="20:00-21:00")
        )
        self.assertEqual(dates, ["2026-11-08"])
        self.assertEqual(slots, ["20:00-21:00"])

    def test_multiple_target_dates_and_slots(self) -> None:
        self.config.target_dates = ["2026-11-06", "2026-11-07"]
        self.config.target_slots = ["18:00-19:00", "19:00-20:00"]
        result = self.monitor.evaluate_snapshot(
            make_snapshot(
                date="2026-11-07",
                time_range="19:00-20:00",
            )
        )
        self.assertEqual(len(result.slots), 1)
        self.assertEqual(result.slots[0].date, "2026-11-07")
        self.assertEqual(result.slots[0].time_range, "19:00-20:00")

    def test_empty_target_dates_match_all_visible_dates(self) -> None:
        self.config.target_dates = []
        self.config.target_slots = []
        result = self.monitor.evaluate_snapshot(
            make_snapshot(
                date="2026-12-01",
                time_range="08:00-09:00",
            )
        )
        self.assertEqual(len(result.slots), 1)
        self.assertEqual(result.slots[0].date, "2026-12-01")


if __name__ == "__main__":
    unittest.main()
