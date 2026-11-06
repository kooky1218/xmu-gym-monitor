from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from src.monitor.config import MonitorConfig, normalize_time_range


LIVE_DATA_SOURCES = frozenset({"network_live", "mini_program_live"})


class SlotAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ReaderLike(Protocol):
    def read_gym_snapshot(self) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class AvailabilitySlot:
    date: str
    venue_id: Any
    stadium_id: int
    slot_id: str
    start_time: str
    end_time: str
    capacity: int | None
    selected_count: int | None
    remaining: int | None
    is_open: bool | None
    data_source: str
    fetched_at: str
    state: SlotAvailability
    notification_eligible: bool
    area_name: str = ""
    time_range: str = ""
    column_id: Any = None
    availability_kind: str = "slot"

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "venue_id": self.venue_id,
            "stadium_id": self.stadium_id,
            "slot_id": self.slot_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "capacity": self.capacity,
            "selected_count": self.selected_count,
            "remaining": self.remaining,
            "is_open": self.is_open,
            "data_source": self.data_source,
            "fetched_at": self.fetched_at,
            "state": self.state.value,
            "notification_eligible": self.notification_eligible,
            "area_name": self.area_name,
            "time_range": self.time_range,
            "column_id": self.column_id,
            "availability_kind": self.availability_kind,
        }


@dataclass(frozen=True)
class MonitorResult:
    slots: tuple[AvailabilitySlot, ...]
    data_source: str
    fetched_at: str
    test_mode: bool

    @property
    def available_slots(self) -> tuple[AvailabilitySlot, ...]:
        return tuple(
            slot for slot in self.slots
            if slot.state is SlotAvailability.AVAILABLE
        )

    @property
    def notification_slots(self) -> tuple[AvailabilitySlot, ...]:
        return tuple(
            slot for slot in self.slots if slot.notification_eligible
        )


class AvailabilityMonitor:
    """Match a normalized StadiumReader snapshot against user criteria."""

    def __init__(self, reader: ReaderLike, config: MonitorConfig) -> None:
        self.reader = reader
        self.config = config

    def read(self) -> MonitorResult:
        snapshot = self.reader.read_gym_snapshot(
            stadium_id=self.config.stadium_id,
            category_id=self.config.category_id,
            target_dates=self.config.target_dates,
        )
        return self.evaluate_snapshot(snapshot)

    def evaluate_snapshot(self, snapshot: dict[str, Any]) -> MonitorResult:
        meta = snapshot.get("meta") or {}
        data_source = str(meta.get("data_source") or "unknown")
        fetched_at = str(
            meta.get("fetched_at") or snapshot.get("fetched_at") or ""
        )
        venue_id = snapshot.get("venue_id")
        stadium_id = int(snapshot.get("stadium_id") or self.config.stadium_id)
        raw_slots = snapshot.get("intervals", {}).get("slots", [])
        target_dates = set(self.config.target_dates)
        target_slots = set(self.config.target_slots)
        matched: list[AvailabilitySlot] = []

        for raw in raw_slots:
            if not isinstance(raw, dict):
                continue
            raw_date = str(raw.get("date") or "")
            raw_time = str(raw.get("time_range") or "")
            availability_kind = str(
                raw.get("availability_kind") or "slot"
            )
            if availability_kind == "date_entry":
                normalized_range = raw_time
            else:
                normalized_range = self._safe_time_range(raw_time)
            if (
                target_dates
                and raw_date not in target_dates
            ) or normalized_range is None:
                continue
            if target_slots and normalized_range not in target_slots:
                continue

            if "-" in normalized_range:
                start_time, end_time = normalized_range.split("-", 1)
            else:
                start_time, end_time = "", ""

            remaining = self._optional_int(
                raw.get("remaining", raw.get("remaining_personal"))
            )
            capacity = self._optional_int(
                raw.get("personal_capacity", raw.get("capacity"))
            )
            selected = self._optional_int(
                raw.get("selected", raw.get("selected_count"))
            )
            raw_is_open = raw.get("is_open")
            is_open = raw_is_open if isinstance(raw_is_open, bool) else None

            if availability_kind == "date_entry" and is_open is not None:
                state = (
                    SlotAvailability.AVAILABLE
                    if is_open
                    else SlotAvailability.UNAVAILABLE
                )
            elif remaining is None or is_open is None:
                state = SlotAvailability.UNKNOWN
            elif is_open and remaining >= self.config.min_remaining:
                state = SlotAvailability.AVAILABLE
            else:
                state = SlotAvailability.UNAVAILABLE

            slot_id = self._slot_id(
                raw,
                date_value=raw_date,
                time_range=raw_time,
            )
            matched.append(
                AvailabilitySlot(
                    date=raw_date,
                    venue_id=venue_id,
                    stadium_id=stadium_id,
                    slot_id=slot_id,
                    start_time=start_time,
                    end_time=end_time,
                    capacity=capacity,
                    selected_count=selected,
                    remaining=remaining,
                    is_open=is_open,
                    data_source=data_source,
                    fetched_at=fetched_at,
                    state=state,
                    notification_eligible=(
                        state is SlotAvailability.AVAILABLE
                        and data_source in LIVE_DATA_SOURCES
                    ),
                    area_name=str(raw.get("area_name") or ""),
                    time_range=normalized_range,
                    column_id=raw.get("column_id"),
                    availability_kind=availability_kind,
                )
            )

        matched.sort(
            key=lambda item: (
                item.date,
                item.start_time,
                item.area_name,
                item.slot_id,
            )
        )
        return MonitorResult(
            slots=tuple(matched),
            data_source=data_source,
            fetched_at=fetched_at,
            test_mode=data_source not in LIVE_DATA_SOURCES,
        )

    @staticmethod
    def discover_options(
        snapshot: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        raw_slots = snapshot.get("intervals", {}).get("slots", [])
        dates = sorted(
            {
                str(slot.get("date"))
                for slot in raw_slots
                if isinstance(slot, dict) and slot.get("date")
            }
        )
        slots = sorted(
            {
                normalize_time_range(str(slot.get("time_range")))
                for slot in raw_slots
                if isinstance(slot, dict)
                and slot.get("time_range")
                and re.match(
                    r"^\s*\d{1,2}:\d{2}\s*(?:-|~|至)\s*\d{1,2}:\d{2}\s*$",
                    str(slot.get("time_range")),
                )
            }
        )
        return dates, slots

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_time_range(value: str) -> str | None:
        try:
            return normalize_time_range(value)
        except ValueError:
            return None

    @staticmethod
    def _slot_id(
        raw: dict[str, Any],
        *,
        date_value: str,
        time_range: str,
    ) -> str:
        interval_id = raw.get("interval_id")
        column_id = raw.get("column_id")
        if interval_id not in (None, "") and column_id not in (None, ""):
            return f"{interval_id}:{column_id}"
        stable = json.dumps(
            {
                "date": date_value,
                "time_range": normalize_time_range(time_range),
                "area_name": raw.get("area_name") or "",
                "column_id": column_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
