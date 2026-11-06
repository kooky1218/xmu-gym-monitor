from __future__ import annotations

from datetime import datetime

from src.monitor.availability_monitor import AvailabilitySlot
from src.monitor.config import MonitorConfig


def build_availability_notification(
    slot: AvailabilitySlot,
    config: MonitorConfig,
    *,
    discovered_at: datetime,
) -> tuple[str, str, str | None]:
    if slot.availability_kind == "date_entry":
        title = "翔安健身房预约入口开放"
        body = (
            f"场馆：{config.stadium_name}\n"
            f"日期：{slot.date}\n"
            "状态：小程序显示“预定”\n"
            "请打开厦大体育小程序选择时段并确认剩余名额。\n"
            f"发现时间：{discovered_at.strftime('%H:%M:%S')}"
        )
    else:
        title = "翔安健身房发现空位"
        body = (
            f"场馆：{config.stadium_name}\n"
            f"日期：{slot.date}\n"
            f"时段：{slot.time_range}\n"
            f"剩余名额：{slot.remaining}\n"
            f"发现时间：{discovered_at.strftime('%H:%M:%S')}"
        )
        if slot.area_name:
            body += f"\n场地：{slot.area_name}"
    return title, body, None


def build_system_error_notification(
    *,
    error_type: str,
    message: str,
    occurred_at: datetime,
) -> tuple[str, str, None]:
    title = "厦大体育空位监控异常"
    body = (
        f"错误类型：{error_type}\n"
        f"说明：{message}\n"
        f"时间：{occurred_at.isoformat(timespec='seconds')}"
    )
    return title, body, None
