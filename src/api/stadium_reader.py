from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import requests

from src.api.cache import CacheEntry, CacheError, SnapshotCache


LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = (
    "https://xdty.xmu.edu.cn/"
    "bdlp_h5_fitness_test/public/index.php"
)
DEFAULT_STADIUM_ID = 16
DEFAULT_CATEGORY_ID = 8
SCHEMA_VERSION = "1.1"
DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parents[2] / "cache" / "latest_snapshot.json"
)


class StadiumReaderError(Exception):
    """Base class for expected reader failures."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class AuthenticationRequiredError(StadiumReaderError):
    """Raised when the remote service requires an approved login session."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, diagnostics=diagnostics)
        self.status = status


class APIResponseError(StadiumReaderError):
    """Raised for a non-success business response."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        info: str | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, diagnostics=diagnostics)
        self.status = status
        self.info = info


class MalformedResponseError(StadiumReaderError):
    """Raised when a response does not match the documented envelope."""


class TransportError(StadiumReaderError):
    """Raised when the HTTP request cannot be completed."""


class AuthenticationAdapter(Protocol):
    """Injection point for an institution-approved authentication mechanism.

    Implementations may configure headers, cookies, client certificates, or an
    official bearer token on the supplied Session. They must not print or log
    credentials. This project deliberately ships no cookie-extraction adapter.
    """

    @property
    def label(self) -> str:
        ...

    def configure(self, session: requests.Session) -> None:
        ...


class NoAuthentication:
    """Default adapter used for anonymous, read-only experiments."""

    @property
    def label(self) -> str:
        return "未配置认证适配器"

    def configure(self, session: requests.Session) -> None:
        return None


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MalformedResponseError(f"字段 {field_name} 不是 JSON 对象")
    return value


def _sequence(value: Any, field_name: str) -> Sequence[Any]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise MalformedResponseError(f"字段 {field_name} 不是 JSON 数组")
    return value


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _status_value(payload: Mapping[str, Any]) -> int | None:
    raw_status = payload.get("status")
    if raw_status is None:
        raise MalformedResponseError("响应缺少 status 字段")
    try:
        return int(raw_status)
    except (TypeError, ValueError) as exc:
        raise MalformedResponseError("响应 status 字段不是整数") from exc


def _auth_message(info: str) -> bool:
    lowered = info.lower()
    keywords = ("登录", "未授权", "失效", "login", "unauthorized")
    return any(keyword in lowered for keyword in keywords)


def _check_envelope(
    payload: Mapping[str, Any],
    operation: str,
) -> Mapping[str, Any]:
    status = _status_value(payload)
    info = _as_text(payload.get("info"))

    if status == -1 or (status == 0 and _auth_message(info)):
        raise AuthenticationRequiredError(
            info or f"{operation} 需要登录",
            status=status,
        )
    if status != 1:
        raise APIResponseError(
            info or f"{operation} 返回业务失败状态 {status}",
            status=status,
            info=info,
        )

    return _mapping(payload.get("data", {}), "data")


def parse_stadium_details(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the getStadiumDetails response into a stable dictionary."""

    data = _check_envelope(payload, "获取场馆详情")
    venues: list[dict[str, Any]] = []
    venue_ids: list[Any] = []

    for venue_index, raw_venue in enumerate(
        _sequence(data.get("venue"), "data.venue")
    ):
        venue = _mapping(raw_venue, f"data.venue[{venue_index}]")
        date_options: list[dict[str, Any]] = []
        for item_index, raw_item in enumerate(
            _sequence(venue.get("list"), f"data.venue[{venue_index}].list")
        ):
            item = _mapping(
                raw_item,
                f"data.venue[{venue_index}].list[{item_index}]",
            )
            venue_id = item.get("venue_id")
            if venue_id not in (None, "") and venue_id not in venue_ids:
                venue_ids.append(venue_id)
            date_options.append(
                {
                    "week": _as_text(item.get("week")),
                    "date": _as_text(item.get("date")),
                    "is_subscribe": _as_int(item.get("is_subscribe")),
                    "venue_id": venue_id,
                }
            )

        category_id = _as_int(venue.get("category_id"))
        venues.append(
            {
                "category_id": category_id,
                "name": _as_text(venue.get("name")),
                "date_options": date_options,
            }
        )

    return {
        "name": _as_text(data.get("name")),
        "details": _as_text(data.get("details")),
        "location": _as_text(data.get("location")),
        "phone": _as_text(data.get("phone")),
        "facilities": _as_text(data.get("facilities")),
        "services": _as_text(data.get("services")),
        "cover": _as_text(data.get("cover")),
        "category_id": _as_int(data.get("category_id")),
        "user_range": data.get("user_range"),
        "albums": list(_sequence(data.get("albums"), "data.albums")),
        "next_url": _as_text(data.get("next_url")),
        "venues": venues,
        "venue_ids": venue_ids,
    }


def _normalize_slot_status(status: str) -> str:
    return {
        "available": "可预约",
        "unavailable": "不可预约",
        "locked": "已锁定",
    }.get(status, status or "未知")


def parse_intervals(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize getInterval while preserving source field names where useful."""

    data = _check_envelope(payload, "获取预约时段")
    personal_capacity = _as_int(data.get("personal_num"))
    team_capacity = _as_int(data.get("team_num"))
    is_can_choose = _as_int(data.get("is_can_choose"))

    dates: list[dict[str, Any]] = []
    for index, raw_date in enumerate(
        _sequence(data.get("date_list"), "data.date_list")
    ):
        item = _mapping(raw_date, f"data.date_list[{index}]")
        dates.append(
            {
                "week": _as_text(item.get("week")),
                "date": _as_text(item.get("date")),
                "date_int": _as_text(item.get("date_int")),
            }
        )

    columns: list[dict[str, Any]] = []
    column_names: dict[str, str] = {}
    for index, raw_column in enumerate(
        _sequence(data.get("column_list"), "data.column_list")
    ):
        item = _mapping(raw_column, f"data.column_list[{index}]")
        column_id = item.get("column_id")
        name = _as_text(item.get("name"))
        columns.append({"column_id": column_id, "name": name})
        column_names[_as_text(column_id)] = name

    groups: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []
    for group_index, raw_group in enumerate(
        _sequence(data.get("time_slot_list"), "data.time_slot_list")
    ):
        group = _mapping(
            raw_group,
            f"data.time_slot_list[{group_index}]",
        )
        group_date = _as_text(group.get("date"))
        group_week = _as_text(group.get("week"))
        group_week_name = _as_text(group.get("week_name"))
        time_range = _as_text(group.get("time_range"))
        normalized_group_slots: list[dict[str, Any]] = []

        for slot_index, raw_slot in enumerate(
            _sequence(
                group.get("slots"),
                f"data.time_slot_list[{group_index}].slots",
            )
        ):
            slot = _mapping(
                raw_slot,
                (
                    f"data.time_slot_list[{group_index}]"
                    f".slots[{slot_index}]"
                ),
            )
            column_id = slot.get("column_id")
            selected = _as_int(slot.get("selected"))
            raw_status = _as_text(slot.get("status"))
            personal_remaining = (
                max(personal_capacity - selected, 0)
                if personal_capacity is not None and selected is not None
                else None
            )
            team_remaining = (
                max(team_capacity - selected, 0)
                if team_capacity is not None and selected is not None
                else None
            )
            normalized = {
                "date": _as_text(slot.get("date"), group_date),
                "week": _as_text(slot.get("week"), group_week),
                "week_name": _as_text(
                    slot.get("week_name"),
                    group_week_name,
                ),
                "time_range": time_range,
                "interval_id": slot.get("interval_id"),
                "column_id": column_id,
                "area_name": _as_text(
                    slot.get("area_name"),
                    column_names.get(_as_text(column_id), ""),
                ),
                "price": _as_float(slot.get("price")),
                "status": raw_status or "unknown",
                "status_text": _normalize_slot_status(raw_status),
                "selected": selected,
                "personal_capacity": personal_capacity,
                "team_capacity": team_capacity,
                "remaining_personal": personal_remaining,
                "remaining_team": team_remaining,
                "remaining": personal_remaining,
                "is_open": bool(
                    is_can_choose not in (0, None)
                    and raw_status == "available"
                    and (personal_remaining is None or personal_remaining > 0)
                ),
                "lock_reason": _as_text(slot.get("lock_reason")),
            }
            normalized_group_slots.append(normalized)
            slots.append(normalized)

        groups.append(
            {
                "date": group_date,
                "week": group_week,
                "week_name": group_week_name,
                "time_range": time_range,
                "slots": normalized_group_slots,
            }
        )

    return {
        "dates": dates,
        "columns": columns,
        "groups": groups,
        "slots": slots,
        "personal_num": personal_capacity,
        "team_num": team_capacity,
        "add_auth": data.get("add_auth"),
        "venue_appointment_min_num": _as_int(
            data.get("venue_appointment_min_num")
        ),
        "confirm_time": _as_text(data.get("confirm_time")),
        "neighbor": data.get("neighbor"),
        "is_can_choose": is_can_choose,
        "is_can_choose_tips": _as_text(data.get("is_can_choose_tips")),
    }


def parse_venue_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _check_envelope(payload, "获取场馆预约配置")
    info = _mapping(data.get("info", {}), "data.info")
    return {
        "need_remark": _as_int(info.get("needRemark")) == 1,
        "is_can_appoint": _as_bool(info.get("isCanAppoint")),
        "is_can_appoint_message": _as_text(info.get("isCanAppointMsg")),
        "phone": _as_text(info.get("phone")),
        "verify_phone": _as_bool(info.get("verify_phone")),
    }


def _error_type(exc: StadiumReaderError) -> str:
    if isinstance(exc, AuthenticationRequiredError):
        return "authentication_required"
    if isinstance(exc, APIResponseError):
        return "business_error"
    if isinstance(exc, MalformedResponseError):
        return "malformed_response"
    if isinstance(exc, TransportError):
        return "transport_error"
    return "reader_error"


class StadiumReader:
    """Low-frequency, read-only adapter for the XMU fitness-test H5 API."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        auth_adapter: AuthenticationAdapter | None = None,
        timeout: float = 15.0,
        min_request_interval: float = 1.0,
        session: requests.Session | None = None,
        trust_env: bool = True,
        cache: SnapshotCache | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_request_interval = max(min_request_interval, 0.0)
        self.auth_adapter = auth_adapter or NoAuthentication()
        self.cache = cache
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = trust_env
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "xmuty-gym-reader/0.1 (read-only client)",
            }
        )
        self.auth_adapter.configure(self.session)
        self._last_request_at: float | None = None
        self._last_http_status: int | None = None
        self._last_business_status: int | None = None
        self._last_request_success = False

    def _begin_request_cycle(self) -> None:
        self._last_http_status = None
        self._last_business_status = None
        self._last_request_success = False

    def _metadata(
        self,
        *,
        data_source: str = "unknown",
        cache_age: int | None = None,
        parse_success: bool,
        error_type: str | None,
        fetched_at: str | None = None,
    ) -> dict[str, Any]:
        return {
            "data_source": data_source,
            "fetched_at": (
                fetched_at
                or datetime.now().astimezone().isoformat(timespec="seconds")
            ),
            "cache_age": cache_age,
            "http_status": self._last_http_status,
            "business_status": self._last_business_status,
            "request_success": self._last_request_success,
            "parse_success": parse_success,
            "error_type": error_type,
        }

    def _attach_error_metadata(
        self,
        exc: StadiumReaderError,
        *,
        parse_success: bool,
    ) -> None:
        if exc.diagnostics is None:
            exc.diagnostics = self._metadata(
                parse_success=parse_success,
                error_type=_error_type(exc),
            )

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        delay = self.min_request_interval - elapsed
        if delay > 0:
            time.sleep(delay)

    def _post_form(
        self,
        path: str,
        data: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self._throttle()
        url = f"{self.base_url}{path}"
        response: requests.Response | None = None
        try:
            response = self.session.post(
                url,
                data=dict(data),
                timeout=self.timeout,
                allow_redirects=True,
            )
            self._last_http_status = response.status_code
            response.raise_for_status()
            self._last_request_success = True
        except requests.exceptions.SSLError as exc:
            transport_error = TransportError(
                "HTTPS/TLS 握手失败，请检查系统代理、VPN 或网络证书设置"
            )
            self._attach_error_metadata(
                transport_error,
                parse_success=False,
            )
            raise transport_error from exc
        except requests.exceptions.ProxyError as exc:
            transport_error = TransportError(
                "系统代理连接失败，请检查代理或 VPN 设置"
            )
            self._attach_error_metadata(
                transport_error,
                parse_success=False,
            )
            raise transport_error from exc
        except requests.RequestException as exc:
            transport_error = TransportError(
                f"请求 {path} 失败：{exc.__class__.__name__}"
            )
            self._attach_error_metadata(
                transport_error,
                parse_success=False,
            )
            raise transport_error from exc
        finally:
            self._last_request_at = time.monotonic()

        if response is None:
            transport_error = TransportError(f"请求 {path} 未返回响应")
            self._attach_error_metadata(
                transport_error,
                parse_success=False,
            )
            raise transport_error
        try:
            payload = response.json()
        except ValueError as exc:
            malformed = MalformedResponseError(
                f"接口 {path} 未返回 JSON"
            )
            self._attach_error_metadata(
                malformed,
                parse_success=False,
            )
            raise malformed from exc
        response_mapping = _mapping(payload, "response")
        raw_status = response_mapping.get("status")
        try:
            self._last_business_status = (
                None if raw_status is None else int(raw_status)
            )
        except (TypeError, ValueError):
            self._last_business_status = None
        return response_mapping

    def get_stadium_details(
        self,
        stadium_id: int = DEFAULT_STADIUM_ID,
    ) -> dict[str, Any]:
        self._begin_request_cycle()
        payload = self._post_form(
            "/index/Stadium/getStadiumDetails",
            {"id": stadium_id},
        )
        try:
            details = parse_stadium_details(payload)
        except StadiumReaderError as exc:
            self._attach_error_metadata(exc, parse_success=False)
            raise
        details["stadium_id"] = stadium_id
        details["meta"] = self._metadata(
            data_source="network_live",
            cache_age=0,
            parse_success=True,
            error_type=None,
        )
        return details

    def get_intervals(
        self,
        *,
        stadium_id: int = DEFAULT_STADIUM_ID,
        venue_id: Any,
        user_range: Any,
        category_id: int = DEFAULT_CATEGORY_ID,
    ) -> dict[str, Any]:
        self._begin_request_cycle()
        payload = self._post_form(
            "/stadium/interval/getInterval",
            {
                "venue_id": venue_id,
                "stadium_id": stadium_id,
                "user_range": user_range,
                "category_id": category_id,
            },
        )
        try:
            intervals = parse_intervals(payload)
        except StadiumReaderError as exc:
            self._attach_error_metadata(exc, parse_success=False)
            raise
        intervals.update(
            {
                "stadium_id": stadium_id,
                "venue_id": venue_id,
                "user_range": user_range,
                "category_id": category_id,
                "meta": self._metadata(
                    data_source="network_live",
                    cache_age=0,
                    parse_success=True,
                    error_type=None,
                ),
            }
        )
        return intervals

    def get_venue_config(
        self,
        *,
        stadium_id: int = DEFAULT_STADIUM_ID,
        venue_id: Any,
        category_id: int = DEFAULT_CATEGORY_ID,
    ) -> dict[str, Any]:
        self._begin_request_cycle()
        payload = self._post_form(
            "/index/Stadium/getVenueConfig",
            {
                "stadium_id": stadium_id,
                "venue_id": venue_id,
                "category_id": category_id,
            },
        )
        try:
            config = parse_venue_config(payload)
        except StadiumReaderError as exc:
            self._attach_error_metadata(exc, parse_success=False)
            raise
        config["meta"] = self._metadata(
            data_source="network_live",
            cache_age=0,
            parse_success=True,
            error_type=None,
        )
        return config

    def read_gym_snapshot(
        self,
        *,
        stadium_id: int = DEFAULT_STADIUM_ID,
        category_id: int = DEFAULT_CATEGORY_ID,
        venue_id: Any | None = None,
        user_range: Any | None = None,
    ) -> dict[str, Any]:
        try:
            details = self.get_stadium_details(stadium_id)
            matching_venue = next(
                (
                    venue
                    for venue in details["venues"]
                    if venue.get("category_id") == category_id
                ),
                None,
            )
            if matching_venue is None:
                raise APIResponseError(
                    f"场馆详情中未找到 category_id={category_id} 的项目"
                )

            resolved_venue_id = venue_id
            if resolved_venue_id in (None, ""):
                resolved_venue_id = next(
                    (
                        item["venue_id"]
                        for item in matching_venue["date_options"]
                        if item.get("venue_id") not in (None, "")
                    ),
                    None,
                )
            if resolved_venue_id in (None, ""):
                raise MalformedResponseError(
                    "未能从场馆详情中取得 venue_id"
                )

            resolved_user_range = (
                user_range
                if user_range is not None
                else details.get("user_range")
            )
            if resolved_user_range is None:
                raise MalformedResponseError(
                    "未能从场馆详情中取得 user_range"
                )

            intervals = self.get_intervals(
                stadium_id=stadium_id,
                venue_id=resolved_venue_id,
                user_range=resolved_user_range,
                category_id=category_id,
            )
        except StadiumReaderError as exc:
            self._attach_error_metadata(exc, parse_success=False)
            raise

        meta = self._metadata(
            data_source="network_live",
            cache_age=0,
            parse_success=True,
            error_type=None,
        )
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "fetched_at": meta["fetched_at"],
            "request_ok": True,
            "campus": details["location"],
            "stadium_id": stadium_id,
            "category_id": category_id,
            "venue_id": resolved_venue_id,
            "user_range": resolved_user_range,
            "venue": {
                "name": details["name"],
                "details": details["details"],
                "facilities": details["facilities"],
                "services": details["services"],
            },
            "details": details,
            "intervals": intervals,
            "meta": meta,
        }
        if self.cache is not None:
            try:
                self.cache.save(snapshot)
            except CacheError:
                LOGGER.warning("成功快照未能写入本地缓存")
        return snapshot

    def load_cached_snapshot(self) -> CacheEntry | None:
        if self.cache is None:
            return None
        return self.cache.load()


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read XMU gym venue data without submitting a booking."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--stadium-id", type=int, default=DEFAULT_STADIUM_ID)
    parser.add_argument("--category-id", type=int, default=DEFAULT_CATEGORY_ID)
    parser.add_argument("--venue-id")
    parser.add_argument("--user-range")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--min-request-interval",
        type=float,
        default=1.0,
    )
    parser.add_argument(
        "--details-only",
        action="store_true",
        help="Only call getStadiumDetails.",
    )
    parser.add_argument(
        "--no-system-proxy",
        action="store_true",
        help="Ignore HTTP(S)_PROXY from the current environment.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Do not persist a successful full snapshot.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")

    args = _build_argument_parser().parse_args(argv)
    cache = None if args.no_cache else SnapshotCache(DEFAULT_CACHE_PATH)
    reader = StadiumReader(
        base_url=args.base_url,
        timeout=args.timeout,
        min_request_interval=args.min_request_interval,
        trust_env=not args.no_system_proxy,
        cache=cache,
    )
    try:
        if args.details_only:
            result = reader.get_stadium_details(args.stadium_id)
        else:
            result = reader.read_gym_snapshot(
                stadium_id=args.stadium_id,
                category_id=args.category_id,
                venue_id=args.venue_id,
                user_range=args.user_range,
            )
    except AuthenticationRequiredError as exc:
        print(
            json.dumps(
                {
                    "request_ok": False,
                    "error_type": "authentication_required",
                    "message": str(exc),
                    "meta": exc.diagnostics,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    except StadiumReaderError as exc:
        print(
            json.dumps(
                {
                    "request_ok": False,
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                    "meta": exc.diagnostics,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
