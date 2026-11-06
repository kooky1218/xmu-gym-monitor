from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.monitor.availability_monitor import (
    AvailabilitySlot,
    LIVE_DATA_SOURCES,
    MonitorResult,
    SlotAvailability,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "monitor_state.sqlite3"


@dataclass(frozen=True)
class PendingNotification:
    slot_key: str
    slot: AvailabilitySlot


class MonitorStateDatabase:
    def __init__(self, path: Path | str = DEFAULT_DATABASE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS slot_state (
                    slot_key TEXT PRIMARY KEY,
                    stadium_id INTEGER NOT NULL,
                    venue_id TEXT,
                    date TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    time_range TEXT NOT NULL,
                    area_name TEXT NOT NULL,
                    last_remaining INTEGER,
                    last_is_open INTEGER,
                    availability_state TEXT NOT NULL,
                    notification_state TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_data_source TEXT NOT NULL,
                    last_notified_at TEXT,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS notification_delivery (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    attempted_at TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    error_type TEXT,
                    provider_message_id TEXT
                );

                CREATE TABLE IF NOT EXISTS system_alert_state (
                    alert_key TEXT PRIMARY KEY,
                    last_attempt_at TEXT NOT NULL,
                    last_success_at TEXT,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS monitor_run (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    data_source TEXT,
                    read_success INTEGER NOT NULL,
                    parse_success INTEGER NOT NULL,
                    matched_count INTEGER NOT NULL,
                    notification_count INTEGER NOT NULL,
                    exit_code INTEGER NOT NULL,
                    error_type TEXT,
                    error_message TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_notification_slot_time
                ON notification_delivery(slot_key, attempted_at);
                """
            )

    def record_run(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        data_source: str | None,
        read_success: bool,
        parse_success: bool,
        matched_count: int,
        notification_count: int,
        exit_code: int,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO monitor_run (
                    started_at, finished_at, data_source, read_success,
                    parse_success, matched_count, notification_count,
                    exit_code, error_type, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at.isoformat(timespec="seconds"),
                    finished_at.isoformat(timespec="seconds"),
                    data_source,
                    int(read_success),
                    int(parse_success),
                    matched_count,
                    notification_count,
                    exit_code,
                    error_type,
                    (error_message or "")[:500] or None,
                ),
            )

    def latest_run(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM monitor_run ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def notification_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM notification_delivery
                WHERE success = 1
                """
            ).fetchone()
        return int(row["count"]) if row else 0

    def get_slot_state(self, slot_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM slot_state WHERE slot_key = ?",
                (slot_key,),
            ).fetchone()
        return dict(row) if row else None


class ChangeDetector:
    """Persist slot states and emit notifications only for live data."""

    def __init__(
        self,
        database: MonitorStateDatabase,
        *,
        cooldown_minutes: int = 30,
    ) -> None:
        self.database = database
        self.cooldown = timedelta(minutes=max(cooldown_minutes, 0))

    def detect(
        self,
        result: MonitorResult,
        *,
        now: datetime | None = None,
    ) -> list[PendingNotification]:
        if result.data_source not in LIVE_DATA_SOURCES:
            return []

        current_time = now or datetime.now().astimezone()
        pending: list[PendingNotification] = []
        with self.database.connect() as connection:
            for slot in result.slots:
                slot_key = self.slot_key(slot)
                previous = connection.execute(
                    "SELECT * FROM slot_state WHERE slot_key = ?",
                    (slot_key,),
                ).fetchone()
                (
                    notification_state,
                    should_notify,
                ) = self._next_notification_state(
                    slot,
                    previous,
                    current_time,
                )
                connection.execute(
                    """
                    INSERT INTO slot_state (
                        slot_key, stadium_id, venue_id, date, slot_id,
                        time_range, area_name, last_remaining, last_is_open,
                        availability_state, notification_state, last_seen_at,
                        last_data_source, last_notified_at, last_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slot_key) DO UPDATE SET
                        last_remaining = excluded.last_remaining,
                        last_is_open = excluded.last_is_open,
                        availability_state = excluded.availability_state,
                        notification_state = excluded.notification_state,
                        last_seen_at = excluded.last_seen_at,
                        last_data_source = excluded.last_data_source
                    """,
                    (
                        slot_key,
                        slot.stadium_id,
                        json.dumps(slot.venue_id, ensure_ascii=False),
                        slot.date,
                        slot.slot_id,
                        slot.time_range,
                        slot.area_name,
                        slot.remaining,
                        None if slot.is_open is None else int(slot.is_open),
                        slot.state.value,
                        notification_state,
                        current_time.isoformat(timespec="seconds"),
                        slot.data_source,
                        (
                            previous["last_notified_at"]
                            if previous
                            else None
                        ),
                        previous["last_error"] if previous else None,
                    ),
                )
                if should_notify:
                    pending.append(PendingNotification(slot_key, slot))
        return pending

    def mark_sent(
        self,
        pending: PendingNotification,
        *,
        title: str,
        body: str,
        sent_at: datetime,
        provider_message_id: str | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE slot_state
                SET notification_state = 'notified',
                    last_notified_at = ?,
                    last_error = NULL
                WHERE slot_key = ?
                """,
                (
                    sent_at.isoformat(timespec="seconds"),
                    pending.slot_key,
                ),
            )
            connection.execute(
                """
                INSERT INTO notification_delivery (
                    slot_key, title, body, attempted_at, success,
                    error_type, provider_message_id
                ) VALUES (?, ?, ?, ?, 1, NULL, ?)
                """,
                (
                    pending.slot_key,
                    title,
                    body,
                    sent_at.isoformat(timespec="seconds"),
                    provider_message_id,
                ),
            )

    def mark_failed(
        self,
        pending: PendingNotification,
        *,
        title: str,
        body: str,
        attempted_at: datetime,
        error_type: str,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE slot_state
                SET notification_state = 'failed',
                    last_error = ?
                WHERE slot_key = ?
                """,
                (error_type[:200], pending.slot_key),
            )
            connection.execute(
                """
                INSERT INTO notification_delivery (
                    slot_key, title, body, attempted_at, success, error_type
                ) VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    pending.slot_key,
                    title,
                    body,
                    attempted_at.isoformat(timespec="seconds"),
                    error_type[:200],
                ),
            )

    def update_run_outcome(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        data_source: str | None,
        read_success: bool,
        parse_success: bool,
        matched_count: int,
        notification_count: int,
        exit_code: int,
        error_type: str | None,
        error_message: str | None,
    ) -> None:
        self.database.record_run(
            started_at=started_at,
            finished_at=finished_at,
            data_source=data_source,
            read_success=read_success,
            parse_success=parse_success,
            matched_count=matched_count,
            notification_count=notification_count,
            exit_code=exit_code,
            error_type=error_type,
            error_message=error_message,
        )

    def should_send_system_alert(
        self,
        alert_key: str,
        *,
        now: datetime,
        cooldown_minutes: int,
    ) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT last_attempt_at
                FROM system_alert_state
                WHERE alert_key = ?
                """,
                (alert_key,),
            ).fetchone()
            if row:
                try:
                    last_attempt = datetime.fromisoformat(
                        row["last_attempt_at"]
                    )
                except ValueError:
                    last_attempt = None
                if last_attempt is not None:
                    elapsed = now - last_attempt
                    if elapsed < timedelta(minutes=cooldown_minutes):
                        return False
            connection.execute(
                """
                INSERT INTO system_alert_state (
                    alert_key, last_attempt_at, last_success_at, last_error
                ) VALUES (?, ?, NULL, NULL)
                ON CONFLICT(alert_key) DO UPDATE SET
                    last_attempt_at = excluded.last_attempt_at
                """,
                (alert_key, now.isoformat(timespec="seconds")),
            )
        return True

    def mark_system_alert_result(
        self,
        alert_key: str,
        *,
        success: bool,
        at: datetime,
        error_type: str | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE system_alert_state
                SET last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END,
                    last_error = ?
                WHERE alert_key = ?
                """,
                (
                    int(success),
                    at.isoformat(timespec="seconds"),
                    error_type,
                    alert_key,
                ),
            )

    @staticmethod
    def slot_key(slot: AvailabilitySlot) -> str:
        venue = json.dumps(slot.venue_id, ensure_ascii=False, sort_keys=True)
        return (
            f"{slot.stadium_id}:{venue}:{slot.date}:"
            f"{slot.slot_id}:{slot.time_range}"
        )

    def _next_notification_state(
        self,
        slot: AvailabilitySlot,
        previous: sqlite3.Row | None,
        now: datetime,
    ) -> tuple[str, bool]:
        current = slot.state.value
        if slot.state is not SlotAvailability.AVAILABLE:
            return "waiting", False

        previous_state = previous["availability_state"] if previous else None
        previous_notification = (
            previous["notification_state"] if previous else None
        )
        last_notified = None
        if previous and previous["last_notified_at"]:
            try:
                last_notified = datetime.fromisoformat(
                    previous["last_notified_at"]
                )
            except ValueError:
                last_notified = None

        changed_to_available = previous_state != current
        retry_pending = previous_notification in {
            "failed",
            "cooldown_suppressed",
        }
        candidate = previous is None or changed_to_available or retry_pending
        if not candidate:
            return "notified", False

        cooldown_ok = (
            last_notified is None
            or now - last_notified >= self.cooldown
        )
        if cooldown_ok:
            return "pending", True
        return "cooldown_suppressed", False
