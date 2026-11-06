from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.monitor.availability_monitor import (
    AvailabilitySlot,
    MonitorResult,
    SlotAvailability,
)
from src.monitor.change_detector import ChangeDetector, MonitorStateDatabase


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 5, 20, 0, tzinfo=TZ)


def make_slot(
    *,
    state: SlotAvailability,
    remaining: int | None,
    column_id: int = 9,
    area_name: str = "健身房",
    source: str = "network_live",
) -> AvailabilitySlot:
    return AvailabilitySlot(
        date="2026-11-06",
        venue_id=123,
        stadium_id=16,
        slot_id=f"77:{column_id}",
        start_time="18:00",
        end_time="19:00",
        capacity=95,
        selected_count=None if remaining is None else 95 - remaining,
        remaining=remaining,
        is_open=state is SlotAvailability.AVAILABLE,
        data_source=source,
        fetched_at=NOW.isoformat(timespec="seconds"),
        state=state,
        notification_eligible=(
            state is SlotAvailability.AVAILABLE
            and source in {"network_live", "mini_program_live"}
        ),
        area_name=area_name,
        time_range="18:00-19:00",
        column_id=column_id,
    )


def make_result(*slots: AvailabilitySlot, source: str = "network_live"):
    return MonitorResult(
        slots=tuple(slots),
        data_source=source,
        fetched_at=NOW.isoformat(timespec="seconds"),
        test_mode=source not in {"network_live", "mini_program_live"},
    )


class ChangeDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "state.sqlite3"
        self.database = MonitorStateDatabase(self.db_path)
        self.detector = ChangeDetector(self.database, cooldown_minutes=30)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _notify(self, pending, at: datetime) -> None:
        self.detector.mark_sent(
            pending,
            title="test",
            body="test",
            sent_at=at,
        )

    def test_first_available_read_triggers_notification(self) -> None:
        pending = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=3)),
            now=NOW,
        )
        self.assertEqual(len(pending), 1)

    def test_miniprogram_live_read_triggers_notification(self) -> None:
        pending = self.detector.detect(
            make_result(
                make_slot(
                    state=SlotAvailability.AVAILABLE,
                    remaining=3,
                    source="mini_program_live",
                ),
                source="mini_program_live",
            ),
            now=NOW,
        )
        self.assertEqual(len(pending), 1)

    def test_continuous_availability_is_deduplicated(self) -> None:
        first = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=3)),
            now=NOW,
        )
        self._notify(first[0], NOW)
        second = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=2)),
            now=NOW + timedelta(minutes=5),
        )
        self.assertEqual(second, [])

    def test_unavailable_updates_state(self) -> None:
        self.detector.detect(
            make_result(make_slot(state=SlotAvailability.UNAVAILABLE, remaining=0)),
            now=NOW,
        )
        key = self.detector.slot_key(
            make_slot(state=SlotAvailability.UNAVAILABLE, remaining=0)
        )
        row = self.database.get_slot_state(key)
        self.assertEqual(row["availability_state"], "unavailable")

    def test_reappears_after_cooldown_triggers_again(self) -> None:
        first = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=3)),
            now=NOW,
        )
        self._notify(first[0], NOW)
        self.detector.detect(
            make_result(make_slot(state=SlotAvailability.UNAVAILABLE, remaining=0)),
            now=NOW + timedelta(minutes=10),
        )
        pending = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=1)),
            now=NOW + timedelta(minutes=31),
        )
        self.assertEqual(len(pending), 1)

    def test_reappears_inside_cooldown_is_suppressed(self) -> None:
        first = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=3)),
            now=NOW,
        )
        self._notify(first[0], NOW)
        self.detector.detect(
            make_result(make_slot(state=SlotAvailability.UNAVAILABLE, remaining=0)),
            now=NOW + timedelta(minutes=5),
        )
        suppressed = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=1)),
            now=NOW + timedelta(minutes=20),
        )
        self.assertEqual(suppressed, [])
        after_cooldown = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=1)),
            now=NOW + timedelta(minutes=31),
        )
        self.assertEqual(len(after_cooldown), 1)

    def test_cache_and_mock_never_trigger(self) -> None:
        for source in ("cache", "mock", "unknown"):
            result = make_result(
                make_slot(
                    state=SlotAvailability.AVAILABLE,
                    remaining=3,
                    source=source,
                ),
                source=source,
            )
            self.assertEqual(self.detector.detect(result, now=NOW), [])

    def test_multiple_areas_are_independent(self) -> None:
        pending = self.detector.detect(
            make_result(
                make_slot(
                    state=SlotAvailability.AVAILABLE,
                    remaining=2,
                    column_id=9,
                    area_name="1号区",
                ),
                make_slot(
                    state=SlotAvailability.AVAILABLE,
                    remaining=4,
                    column_id=10,
                    area_name="2号区",
                ),
            ),
            now=NOW,
        )
        self.assertEqual(len(pending), 2)
        self.assertNotEqual(pending[0].slot_key, pending[1].slot_key)

    def test_state_survives_detector_restart(self) -> None:
        first = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=3)),
            now=NOW,
        )
        self._notify(first[0], NOW)

        new_database = MonitorStateDatabase(self.db_path)
        new_detector = ChangeDetector(new_database, cooldown_minutes=30)
        pending = new_detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=3)),
            now=NOW + timedelta(minutes=5),
        )
        self.assertEqual(pending, [])

    def test_failed_delivery_can_retry_next_run(self) -> None:
        first = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=3)),
            now=NOW,
        )
        self.detector.mark_failed(
            first[0],
            title="test",
            body="test",
            attempted_at=NOW,
            error_type="network_error",
        )
        retry = self.detector.detect(
            make_result(make_slot(state=SlotAvailability.AVAILABLE, remaining=3)),
            now=NOW + timedelta(minutes=5),
        )
        self.assertEqual(len(retry), 1)

    def test_unknown_state_does_not_trigger(self) -> None:
        pending = self.detector.detect(
            make_result(
                make_slot(state=SlotAvailability.UNKNOWN, remaining=None)
            ),
            now=NOW,
        )
        self.assertEqual(pending, [])


if __name__ == "__main__":
    unittest.main()
