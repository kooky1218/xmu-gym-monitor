from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from src.api.stadium_reader import (
    AuthenticationRequiredError,
    TransportError,
)
from src.monitor.change_detector import MonitorStateDatabase
from src.monitor.config import MonitorConfig
from src.notification.bark_notifier import BarkNotificationResult
from src.service.background_worker import (
    InstanceAlreadyRunning,
    MonitorRunner,
    process_snapshot_notifications,
    run_daemon,
    single_instance_lock,
    simulate_notification,
)


def snapshot(source: str = "network_live") -> dict:
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
                    "date": "2026-11-06",
                    "time_range": "18:00-19:00",
                    "interval_id": 77,
                    "column_id": 9,
                    "area_name": "健身房",
                    "personal_capacity": 95,
                    "selected": 92,
                    "remaining": 3,
                    "is_open": True,
                }
            ]
        },
    }


class MockReader:
    def __init__(self, results: list[object]) -> None:
        self.results = results
        self.calls = 0

    def read_gym_snapshot(self, **kwargs) -> dict:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeNotifier:
    def __init__(
        self,
        *,
        success: bool = True,
    ) -> None:
        self.success = success
        self.calls: list[dict] = []

    def send(self, **kwargs) -> BarkNotificationResult:
        self.calls.append(kwargs)
        return BarkNotificationResult(
            success=self.success,
            status_code=200 if self.success else 500,
            attempts=1,
            error_type=None if self.success else "server_error",
        )


class BackgroundWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "monitor.sqlite3"
        self.config = MonitorConfig(
            target_dates=["2026-11-06"],
            target_slots=["18:00-19:00"],
            enabled=True,
            notify_on_system_error=False,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_runner(
        self,
        reader,
        notifier=None,
        *,
        sleeps=None,
    ) -> MonitorRunner:
        return MonitorRunner(
            config=self.config,
            database=MonitorStateDatabase(self.db_path),
            reader=reader,
            credential_store=object(),
            notifier=notifier,
            sleeper=(sleeps.append if sleeps is not None else lambda _: None),
        )

    def test_disabled_monitor_does_not_read(self) -> None:
        self.config.enabled = False
        reader = MockReader([])
        result = self.make_runner(reader).run_once()
        self.assertEqual(result.status, "disabled")
        self.assertEqual(reader.calls, 0)

    def test_live_availability_sends_notification(self) -> None:
        notifier = FakeNotifier()
        result = self.make_runner(MockReader([snapshot()]), notifier).run_once()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.status, "NOTIFIED")
        self.assertEqual(result.notification_count, 1)
        self.assertEqual(len(notifier.calls), 1)
        self.assertIn("剩余名额：3", notifier.calls[0]["body"])
        self.assertIsNone(notifier.calls[0].get("url"))

    def test_date_entry_notification_does_not_claim_remaining_count(
        self,
    ) -> None:
        self.config.target_slots = []
        date_snapshot = snapshot(source="mini_program_live")
        slot = date_snapshot["intervals"]["slots"][0]
        slot.update(
            {
                "time_range": "日期可预约",
                "remaining": None,
                "selected": None,
                "personal_capacity": None,
                "is_open": True,
                "availability_kind": "date_entry",
            }
        )
        notifier = FakeNotifier()
        result = self.make_runner(
            MockReader([date_snapshot]),
            notifier,
        ).run_once()
        self.assertEqual(result.status, "NOTIFIED")
        self.assertEqual(len(notifier.calls), 1)
        self.assertIn("预约入口开放", notifier.calls[0]["title"])
        self.assertIn("请打开厦大体育小程序选择时段", notifier.calls[0]["body"])
        self.assertNotIn("剩余名额：", notifier.calls[0]["body"])

    def test_existing_snapshot_can_trigger_manual_notification(
        self,
    ) -> None:
        config_path = Path(self.temp.name) / "manual-config.json"
        database_path = Path(self.temp.name) / "manual.sqlite3"
        self.config.save(config_path)
        notifier = FakeNotifier()
        result = process_snapshot_notifications(
            snapshot(),
            config_path=config_path,
            database_path=database_path,
            credential_store=object(),
            notifier=notifier,
        )
        self.assertEqual(result.status, "NOTIFIED")
        self.assertEqual(result.notification_count, 1)
        self.assertEqual(len(notifier.calls), 1)
        self.assertIn("18:00-19:00", notifier.calls[0]["body"])
        self.assertIsNone(notifier.calls[0].get("url"))

    def test_mock_and_cache_only_enter_test_mode(self) -> None:
        for source in ("mock", "cache"):
            notifier = FakeNotifier()
            result = self.make_runner(
                MockReader([snapshot(source)]),
                notifier,
            ).run_once()
            self.assertEqual(result.status, "TEST_MODE")
            self.assertEqual(notifier.calls, [])

    def test_authentication_failure_does_not_send_availability(self) -> None:
        notifier = FakeNotifier()
        error = AuthenticationRequiredError("login expired")
        result = self.make_runner(MockReader([error]), notifier).run_once()
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.status, "AUTH_REQUIRED")
        self.assertEqual(notifier.calls, [])

    def test_authentication_failure_can_send_system_alert_once(self) -> None:
        self.config.notify_on_system_error = True
        notifier = FakeNotifier()
        error = AuthenticationRequiredError("login expired")
        runner = self.make_runner(MockReader([error]), notifier)
        first = runner.run_once()
        second = self.make_runner(
            MockReader([AuthenticationRequiredError("login expired")]),
            notifier,
        ).run_once()
        self.assertEqual(first.exit_code, 2)
        self.assertEqual(second.exit_code, 2)
        self.assertEqual(len(notifier.calls), 1)
        self.assertIn("异常", notifier.calls[0]["title"])

    def test_network_interruption_retries_then_fails(self) -> None:
        sleeps: list[float] = []
        errors = []
        for _ in range(3):
            error = TransportError("offline")
            error.diagnostics = {"error_type": "transport_error"}
            errors.append(error)
        reader = MockReader(errors)
        result = self.make_runner(reader, sleeps=sleeps).run_once()
        self.assertEqual(result.exit_code, 5)
        self.assertEqual(reader.calls, 3)
        self.assertEqual(len(sleeps), 2)

    def test_rate_limit_uses_longer_backoff(self) -> None:
        sleeps: list[float] = []
        errors = []
        for _ in range(3):
            error = TransportError("rate limited")
            error.diagnostics = {
                "error_type": "transport_error",
                "http_status": 429,
            }
            errors.append(error)
        result = self.make_runner(
            MockReader(errors),
            sleeps=sleeps,
        ).run_once()
        self.assertEqual(result.exit_code, 5)
        self.assertEqual(sleeps, [15.0, 30.0])

    def test_notification_failure_returns_exit_code_6(self) -> None:
        result = self.make_runner(
            MockReader([snapshot()]),
            FakeNotifier(success=False),
        ).run_once()
        self.assertEqual(result.exit_code, 6)
        self.assertEqual(result.status, "NOTIFICATION_PARTIAL_FAILURE")

    def test_repeated_live_availability_is_deduplicated(self) -> None:
        notifier = FakeNotifier()
        self.make_runner(MockReader([snapshot()]), notifier).run_once()
        second = self.make_runner(
            MockReader([snapshot()]),
            notifier,
        ).run_once()
        self.assertEqual(second.status, "NO_NEW_AVAILABILITY")
        self.assertEqual(len(notifier.calls), 1)

    def test_simulation_uses_fake_notifier(self) -> None:
        self.config.target_dates = ["2026-11-06"]
        self.config.target_slots = ["18:00-19:00"]
        notifier = FakeNotifier()
        result = simulate_notification(
            self.config,
            credential_store=object(),
            notifier=notifier,
        )
        self.assertEqual(result.status, "SIMULATION_SENT")
        self.assertEqual(len(notifier.calls), 1)
        self.assertIn("测试模式", notifier.calls[0]["body"])
        self.assertIsNone(notifier.calls[0].get("url"))

    def test_single_instance_lock_rejects_second_owner(self) -> None:
        lock_path = Path(self.temp.name) / "monitor.lock"
        with single_instance_lock(lock_path):
            with self.assertRaises(InstanceAlreadyRunning):
                with single_instance_lock(lock_path):
                    pass

    def test_daemon_stops_cleanly_when_requested(self) -> None:
        event = threading.Event()
        event.set()
        result = run_daemon(
            config_path=Path(self.temp.name) / "daemon-config.json",
            database_path=Path(self.temp.name) / "daemon.sqlite3",
            lock_path=Path(self.temp.name) / "daemon.lock",
            stop_event=event,
        )
        self.assertEqual(result, 0)

    def test_daemon_waits_for_next_check_when_disabled(self) -> None:
        config_path = Path(self.temp.name) / "daemon-config.json"
        disabled = MonitorConfig(enabled=False)
        disabled.save(config_path)
        event = threading.Event()
        waits: list[float] = []

        def sleeper(seconds: float) -> bool:
            waits.append(seconds)
            event.set()
            return True

        result = run_daemon(
            config_path=config_path,
            database_path=Path(self.temp.name) / "daemon.sqlite3",
            lock_path=Path(self.temp.name) / "daemon.lock",
            stop_event=event,
            sleeper=sleeper,
        )
        self.assertEqual(result, 0)
        self.assertEqual(waits, [300])


if __name__ == "__main__":
    unittest.main()
