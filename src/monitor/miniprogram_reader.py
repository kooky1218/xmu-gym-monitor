from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from src.api.cache import CacheError, SnapshotCache
from src.api.stadium_reader import (
    AuthenticationRequiredError,
    StadiumReaderError,
)
from src.monitor.miniprogram_ui_reader import (
    MiniProgramUiError,
    MiniProgramUiReader,
    MiniProgramUiSnapshot,
    MiniProgramWindowNotFound,
)


DEFAULT_STADIUM_ID = 16
DEFAULT_CATEGORY_ID = 8
VENUE_NAME = "翔安校区健身房"
CAMPUS_NAME = "翔安校区"
DETAIL_PAGE = "场馆详情"
CHOOSE_PAGE = "选择场次"
DATE_ENTRY_UNAVAILABLE_LABELS = {"暂无", "不可预约", "已满", "未开放"}
DATE_ENTRY_AVAILABLE_LABELS = {"预定", "预约", "可预约"}
_DATE_TEXT_RE = re.compile(r"^\s*(\d{1,2})月(\d{1,2})日\s*$")
_ISO_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")
_TIME_RANGE_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$"
)
_FRACTION_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")
_AUTH_MARKERS = (
    "登录信息失效",
    "登录已失效",
    "请重新登录",
    "授权登录",
    "统一身份认证",
    "session expired",
)


class MiniProgramReaderError(StadiumReaderError):
    """Raised when the live mini-program page cannot be interpreted."""


class MiniProgramUnavailableError(MiniProgramReaderError):
    """Raised when WeChat or the mini-program window is unavailable."""


class MiniProgramAuthenticationRequiredError(AuthenticationRequiredError):
    """Raised when the mini-program page asks the user to sign in again."""


def _page_has_auth_marker(texts: Iterable[str]) -> bool:
    text = "\n".join(texts)
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _AUTH_MARKERS)


def _is_date_label(value: str) -> bool:
    return bool(
        _DATE_TEXT_RE.fullmatch(value)
        or _ISO_DATE_RE.fullmatch(value)
    )


def _resolve_date(value: str, *, today: date) -> str | None:
    iso_match = _ISO_DATE_RE.fullmatch(value)
    if iso_match:
        try:
            return date(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3)),
            ).isoformat()
        except ValueError:
            return None

    month_day = _DATE_TEXT_RE.fullmatch(value)
    if not month_day:
        return None
    try:
        candidate = date(
            today.year,
            int(month_day.group(1)),
            int(month_day.group(2)),
        )
    except ValueError:
        return None
    if (today - candidate).days > 60:
        try:
            candidate = candidate.replace(year=today.year + 1)
        except ValueError:
            return None
    return candidate.isoformat()


def parse_detail_dates(
    texts: Iterable[str],
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Parse date-level booking entries from the venue detail page."""

    values = [str(value).strip() for value in texts]
    current_date = today or datetime.now().astimezone().date()
    rows: list[dict[str, Any]] = []
    action_occurrences: dict[str, int] = {}

    date_indexes = [
        index for index, value in enumerate(values) if _is_date_label(value)
    ]
    for position, index in enumerate(date_indexes):
        end = (
            date_indexes[position + 1]
            if position + 1 < len(date_indexes)
            else min(len(values), index + 6)
        )
        week = values[index - 1] if index > 0 else ""
        if _is_date_label(week) or len(week) > 8:
            week = ""

        action = ""
        for candidate in values[index + 1 : end]:
            normalized = candidate.strip()
            if (
                normalized in DATE_ENTRY_AVAILABLE_LABELS
                or normalized in DATE_ENTRY_UNAVAILABLE_LABELS
            ):
                action = normalized
                break
        if not action:
            continue
        action_occurrence = action_occurrences.get(action, 0)
        action_occurrences[action] = action_occurrence + 1

        iso_date = _resolve_date(values[index], today=current_date)
        if iso_date is None:
            continue
        is_open = action in DATE_ENTRY_AVAILABLE_LABELS
        rows.append(
            {
                "date": iso_date,
                "date_text": values[index],
                "week": week,
                "action_text": action,
                "action_occurrence": action_occurrence,
                "is_open": is_open,
            }
        )
    return rows


def parse_date_tabs(
    texts: Iterable[str],
    *,
    today: date | None = None,
) -> list[dict[str, str]]:
    """Parse the date tabs shown at the top of the choose page."""

    values = [str(value).strip() for value in texts]
    current_date = today or datetime.now().astimezone().date()
    rows: list[dict[str, str]] = []
    for index, value in enumerate(values):
        if not _is_date_label(value):
            continue
        week = values[index - 1] if index > 0 else ""
        if _is_date_label(week) or len(week) > 8:
            week = ""
        iso_date = _resolve_date(value, today=current_date)
        if iso_date is None:
            continue
        rows.append(
            {
                "date": iso_date,
                "date_text": value,
                "week": week,
            }
        )
    return rows


def parse_choose_slots(
    texts: Iterable[str],
    *,
    selected_date: str,
    week: str = "",
) -> list[dict[str, Any]]:
    """Best-effort parser for the visible slot grid on the choose page."""

    values = [str(value).strip() for value in texts]
    ranges: list[tuple[int, str, int, int]] = []
    for index, value in enumerate(values):
        match = _TIME_RANGE_RE.fullmatch(value)
        if match:
            ranges.append(
                (
                    index,
                    f"{match.group(1)}-{match.group(2)}",
                    int(match.group(1).split(":")[0]),
                    int(match.group(2).split(":")[0]),
                )
            )

    slots: list[dict[str, Any]] = []
    for range_position, (index, time_range, start_hour, end_hour) in enumerate(
        ranges
    ):
        next_index = (
            ranges[range_position + 1][0]
            if range_position + 1 < len(ranges)
            else min(len(values), index + 12)
        )
        fractions: list[tuple[int, int]] = []
        for candidate in values[index + 1 : next_index]:
            match = _FRACTION_RE.fullmatch(candidate)
            if match:
                fractions.append((int(match.group(1)), int(match.group(2))))
        for column_index, (selected, capacity) in enumerate(fractions):
            remaining = max(capacity - selected, 0)
            slots.append(
                {
                    "date": selected_date,
                    "week": week,
                    "week_name": week,
                    "time_range": time_range,
                    "interval_id": f"{selected_date}:{time_range}",
                    "column_id": column_index,
                    "area_name": f"场地{column_index + 1}",
                    "price": None,
                    "status": "available" if remaining > 0 else "unavailable",
                    "status_text": (
                        "可预约" if remaining > 0 else "不可预约"
                    ),
                    "selected": selected,
                    "personal_capacity": capacity,
                    "team_capacity": None,
                    "remaining_personal": remaining,
                    "remaining_team": None,
                    "remaining": remaining,
                    "is_open": remaining > 0,
                    "lock_reason": "",
                    "availability_kind": "slot",
                    "start_hour": start_hour,
                    "end_hour": end_hour,
                }
            )
    return slots


def detail_rows_to_slots(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert date-level entries into conservative normalized monitor slots."""

    slots: list[dict[str, Any]] = []
    for row in rows:
        is_open = bool(row.get("is_open"))
        raw_date = str(row.get("date") or "")
        slots.append(
            {
                "date": raw_date,
                "week": str(row.get("week") or ""),
                "week_name": str(row.get("week") or ""),
                "time_range": "日期可预约" if is_open else "暂无预约",
                "interval_id": f"date-entry:{raw_date}",
                "column_id": "date-entry",
                "area_name": "",
                "price": None,
                "status": "available" if is_open else "unavailable",
                "status_text": (
                    "预约入口开放" if is_open else "暂无预约"
                ),
                "selected": None,
                "personal_capacity": None,
                "team_capacity": None,
                "remaining_personal": None,
                "remaining_team": None,
                "remaining": None,
                "is_open": is_open,
                "lock_reason": "",
                "availability_kind": "date_entry",
            }
        )
    return slots


class MiniProgramStadiumReader:
    """Read the active mini-program page without extracting WeChat credentials."""

    auth_adapter_label = "微信小程序登录态（只读 UI）"

    def __init__(
        self,
        *,
        ui_reader: MiniProgramUiReader | None = None,
        cache: SnapshotCache | None = None,
        navigation_wait_seconds: float = 0.8,
    ) -> None:
        self.ui_reader = ui_reader or MiniProgramUiReader()
        self.cache = cache
        self.navigation_wait_seconds = max(navigation_wait_seconds, 0)

    @property
    def auth_adapter(self):
        return self

    @property
    def label(self) -> str:
        return self.auth_adapter_label

    def read_gym_snapshot(
        self,
        *,
        stadium_id: int = DEFAULT_STADIUM_ID,
        category_id: int = DEFAULT_CATEGORY_ID,
        target_dates: list[str] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        try:
            snapshot = self.ui_reader.capture()
            snapshot = self._ensure_venue_page(snapshot)
            payload = self._snapshot_from_page(
                snapshot,
                stadium_id=stadium_id,
                category_id=category_id,
                target_dates=target_dates or [],
            )
        except AuthenticationRequiredError:
            raise
        except MiniProgramWindowNotFound as exc:
            raise MiniProgramUnavailableError(
                str(exc),
                diagnostics=self._error_meta(
                    error_type="miniprogram_window_not_found"
                ),
            ) from exc
        except MiniProgramUiError as exc:
            raise MiniProgramUnavailableError(
                str(exc),
                diagnostics=self._error_meta(
                    error_type="miniprogram_ui_error"
                ),
            ) from exc
        except StadiumReaderError:
            raise
        except Exception as exc:
            raise MiniProgramReaderError(
                f"小程序页面解析失败：{exc.__class__.__name__}",
                diagnostics=self._error_meta(
                    error_type="miniprogram_parse_error"
                ),
            ) from exc

        if self.cache is not None:
            try:
                self.cache.save(payload)
            except CacheError:
                pass
        return payload

    def load_cached_snapshot(self):
        if self.cache is None:
            return None
        return self.cache.load()

    def _ensure_venue_page(
        self,
        snapshot: MiniProgramUiSnapshot,
    ) -> MiniProgramUiSnapshot:
        for _attempt in range(3):
            self._raise_for_auth_or_wrong_page(snapshot)
            if snapshot.page_kind in {"detail", "choose"}:
                return snapshot

            if (
                snapshot.page_kind == "venue_list"
                and VENUE_NAME in snapshot.texts
            ):
                snapshot = self.ui_reader.click(VENUE_NAME)
                self._wait()
                self._raise_for_auth_or_wrong_page(snapshot)
                continue
            if "场馆预约" in snapshot.texts:
                snapshot = self.ui_reader.click("场馆预约")
                self._wait()
                self._raise_for_auth_or_wrong_page(snapshot)
                continue
            if VENUE_NAME in snapshot.texts:
                snapshot = self.ui_reader.click(VENUE_NAME)
                self._wait()
                self._raise_for_auth_or_wrong_page(snapshot)
                continue
            raise MiniProgramReaderError(
                "当前小程序页面既不是场馆列表，也不是翔安校区健身房详情",
                diagnostics=self._error_meta(
                    error_type="miniprogram_page_unknown"
                ),
            )
        raise MiniProgramReaderError(
            "无法自动进入翔安校区健身房详情页",
            diagnostics=self._error_meta(
                error_type="miniprogram_navigation_failed"
            ),
        )

    @staticmethod
    def _raise_for_auth_or_wrong_page(
        snapshot: MiniProgramUiSnapshot,
    ) -> None:
        if _page_has_auth_marker(snapshot.texts):
            raise MiniProgramAuthenticationRequiredError(
                "小程序登录态已失效，请打开厦大体育并重新登录",
                diagnostics={
                    "data_source": "unknown",
                    "fetched_at": datetime.now().astimezone().isoformat(
                        timespec="seconds"
                    ),
                    "cache_age": None,
                    "http_status": None,
                    "business_status": None,
                    "request_success": True,
                    "parse_success": False,
                    "error_type": "authentication_required",
                },
            )
        if (
            snapshot.page_kind == "detail"
            and VENUE_NAME not in snapshot.page_text
        ):
            raise MiniProgramReaderError(
                "当前场馆详情不是翔安校区健身房",
                diagnostics={
                    "data_source": "unknown",
                    "fetched_at": datetime.now().astimezone().isoformat(
                        timespec="seconds"
                    ),
                    "cache_age": None,
                    "http_status": None,
                    "business_status": None,
                    "request_success": True,
                    "parse_success": False,
                    "error_type": "wrong_venue",
                },
            )

    def _snapshot_from_page(
        self,
        snapshot: MiniProgramUiSnapshot,
        *,
        stadium_id: int,
        category_id: int,
        target_dates: list[str],
    ) -> dict[str, Any]:
        if snapshot.page_kind == "choose":
            slots, dates, final_snapshot = self._collect_choose_slots(
                snapshot,
                target_dates=target_dates,
            )
            return self._build_snapshot_payload(
                snapshot=final_snapshot,
                stadium_id=stadium_id,
                category_id=category_id,
                dates=dates,
                slots=slots,
                source_page="choose" if slots else "detail",
            )

        dates = parse_detail_dates(snapshot.texts)
        if not dates:
            raise MiniProgramReaderError(
                "场馆详情页中没有识别到日期状态",
                diagnostics=self._error_meta(
                    error_type="miniprogram_dates_not_found"
                ),
            )
        target_set = set(target_dates)
        bookable = [
            row
            for row in dates
            if row.get("is_open")
            and (not target_set or row.get("date") in target_set)
        ]
        if bookable:
            first = bookable[0]
            try:
                choose_snapshot = self.ui_reader.click(
                    str(first["action_text"]),
                    occurrence=int(first.get("action_occurrence", 0)),
                )
                self._wait()
                if choose_snapshot.page_kind == "choose":
                    (
                        slots,
                        choose_dates,
                        final_snapshot,
                    ) = self._collect_choose_slots(
                        choose_snapshot,
                        target_dates=target_dates,
                        initial_date=str(first["date"]),
                    )
                    if slots:
                        return self._build_snapshot_payload(
                            snapshot=final_snapshot,
                            stadium_id=stadium_id,
                            category_id=category_id,
                            dates=choose_dates,
                            slots=slots,
                            source_page="choose",
                        )
            except MiniProgramUiError:
                pass

        return self._build_snapshot_payload(
            snapshot=snapshot,
            stadium_id=stadium_id,
            category_id=category_id,
            dates=dates,
            slots=detail_rows_to_slots(dates),
            source_page="detail",
        )

    def _collect_choose_slots(
        self,
        snapshot: MiniProgramUiSnapshot,
        *,
        target_dates: list[str] | None = None,
        initial_date: str | None = None,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, str]],
        MiniProgramUiSnapshot,
    ]:
        target_set = set(target_dates or [])
        dates = parse_date_tabs(snapshot.texts)
        selected_dates = [
            row
            for row in dates
            if not target_set or row["date"] in target_set
        ]
        if not selected_dates:
            return [], dates, snapshot

        current_date = initial_date
        current_snapshot = snapshot
        if current_date is None:
            first = selected_dates[0]
            current_date = first["date"]
            try:
                current_snapshot = self.ui_reader.click(first["date_text"])
                self._wait()
            except MiniProgramUiError:
                current_snapshot = snapshot

        collected: list[dict[str, Any]] = []
        for row in selected_dates:
            if row["date"] != current_date:
                try:
                    clicked = self.ui_reader.click(row["date_text"])
                    self._wait()
                except MiniProgramUiError:
                    continue
                if clicked.page_kind != "choose":
                    continue
                current_snapshot = clicked
                current_date = row["date"]

            visible_slots = parse_choose_slots(
                current_snapshot.texts,
                selected_date=row["date"],
                week=row.get("week", ""),
            )
            collected.extend(visible_slots)

        deduplicated: dict[tuple[str, str, str], dict[str, Any]] = {}
        for slot in collected:
            key = (
                str(slot.get("date") or ""),
                str(slot.get("time_range") or ""),
                str(slot.get("column_id") or ""),
            )
            deduplicated[key] = slot
        return (
            sorted(
                deduplicated.values(),
                key=lambda item: (
                    str(item.get("date") or ""),
                    str(item.get("time_range") or ""),
                    str(item.get("column_id") or ""),
                ),
            ),
            dates,
            current_snapshot,
        )

    def _build_snapshot_payload(
        self,
        *,
        snapshot: MiniProgramUiSnapshot,
        stadium_id: int,
        category_id: int,
        dates: list[dict[str, Any]],
        slots: list[dict[str, Any]],
        source_page: str,
    ) -> dict[str, Any]:
        meta = self._success_meta(snapshot=snapshot, source_page=source_page)
        return {
            "schema_version": "miniprogram-1.0",
            "fetched_at": meta["fetched_at"],
            "request_ok": True,
            "campus": CAMPUS_NAME,
            "stadium_id": stadium_id,
            "category_id": category_id,
            "venue_id": "miniprogram-ui",
            "venue": {
                "name": VENUE_NAME,
                "details": "",
                "facilities": "",
                "services": "",
            },
            "details": {
                "dates": dates,
                "page_kind": source_page,
            },
            "intervals": {
                "dates": dates,
                "columns": [],
                "groups": [],
                "slots": slots,
                "source_page": source_page,
            },
            "meta": meta,
        }

    def _wait(self) -> None:
        if self.navigation_wait_seconds:
            time.sleep(self.navigation_wait_seconds)

    @staticmethod
    def _success_meta(
        *,
        snapshot: MiniProgramUiSnapshot,
        source_page: str,
    ) -> dict[str, Any]:
        return {
            "data_source": "mini_program_live",
            "fetched_at": snapshot.fetched_at,
            "cache_age": 0,
            "http_status": None,
            "business_status": None,
            "request_success": True,
            "parse_success": True,
            "error_type": None,
            "ui_source": snapshot.source,
            "page_kind": source_page,
        }

    @staticmethod
    def _error_meta(*, error_type: str) -> dict[str, Any]:
        return {
            "data_source": "unknown",
            "fetched_at": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "cache_age": None,
            "http_status": None,
            "business_status": None,
            "request_success": False,
            "parse_success": False,
            "error_type": error_type,
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read the logged-in XMU sports mini-program page"
    )
    parser.add_argument("--stadium-id", type=int, default=DEFAULT_STADIUM_ID)
    parser.add_argument("--category-id", type=int, default=DEFAULT_CATEGORY_ID)
    parser.add_argument("--target-date", action="append", default=[])
    parser.add_argument("--no-cache", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = _build_parser().parse_args(argv)
    cache = (
        None
        if args.no_cache
        else SnapshotCache(
            Path(__file__).resolve().parents[2]
            / "cache"
            / "miniprogram_latest.json"
        )
    )
    reader = MiniProgramStadiumReader(cache=cache)
    try:
        payload = reader.read_gym_snapshot(
            stadium_id=args.stadium_id,
            category_id=args.category_id,
            target_dates=args.target_date,
        )
    except StadiumReaderError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "message": str(exc),
                    "meta": exc.diagnostics or {},
                },
                ensure_ascii=False,
            )
        )
        return 2 if isinstance(exc, AuthenticationRequiredError) else 5
    print(json.dumps({"ok": True, "snapshot": payload}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
