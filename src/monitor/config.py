from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "monitor_config.json"
_TIME_RANGE_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2})\s*(?:-|~|至)\s*(\d{1,2}:\d{2})\s*$"
)


class MonitorConfigError(ValueError):
    """Raised when monitor configuration is invalid."""


def normalize_time_range(value: str) -> str:
    match = _TIME_RANGE_RE.match(value)
    if not match:
        raise MonitorConfigError(
            f"无效时段 {value!r}，应使用 HH:MM-HH:MM"
        )
    start, end = match.group(1), match.group(2)
    return f"{start}-{end}"


@dataclass
class MonitorConfig:
    stadium_id: int = 16
    category_id: int = 8
    campus: str = "翔安校区"
    stadium_name: str = "爱秋体育馆健身房"
    timezone: str = "Asia/Shanghai"
    check_interval_minutes: int = 5
    min_remaining: int = 1
    target_dates: list[str] = field(default_factory=list)
    target_slots: list[str] = field(default_factory=list)
    enabled: bool = False
    notification_cooldown_minutes: int = 30
    notify_on_system_error: bool = True
    system_error_cooldown_minutes: int = 60
    bark_service_url: str = "https://api.day.app"
    notification_jump_url: str = (
        "https://xdty.xmu.edu.cn/"
        "bdlp_h5_fitness_test/view/stadium/"
        "detail.html?id=16&category_id=8"
    )

    def validate(self) -> None:
        if self.stadium_id <= 0:
            raise MonitorConfigError("stadium_id 必须大于 0")
        if self.category_id < 0:
            raise MonitorConfigError("category_id 不能小于 0")
        if self.check_interval_minutes < 5:
            raise MonitorConfigError("检查间隔不得低于 5 分钟")
        if self.min_remaining < 1:
            raise MonitorConfigError("最低剩余名额不得低于 1")
        if self.notification_cooldown_minutes < 0:
            raise MonitorConfigError("通知冷却时间不能小于 0")
        if self.system_error_cooldown_minutes < 0:
            raise MonitorConfigError("系统异常冷却时间不能小于 0")
        if not self.bark_service_url.startswith(("https://", "http://")):
            raise MonitorConfigError("Bark 服务地址必须使用 HTTP(S)")
        if self.notification_jump_url and not self.notification_jump_url.startswith(
            ("https://", "http://")
        ):
            raise MonitorConfigError("通知跳转 URL 必须使用 HTTP(S)")

        normalized_dates: list[str] = []
        for value in self.target_dates:
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise MonitorConfigError(
                    f"无效日期 {value!r}，应使用 YYYY-MM-DD"
                ) from exc
            text = parsed.isoformat()
            if text not in normalized_dates:
                normalized_dates.append(text)

        normalized_slots: list[str] = []
        for value in self.target_slots:
            text = normalize_time_range(value)
            if text not in normalized_slots:
                normalized_slots.append(text)

        self.target_dates = sorted(normalized_dates)
        self.target_slots = sorted(normalized_slots)

    def to_dict(self, *, include_secrets: bool = False) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MonitorConfig":
        allowed = set(cls.__dataclass_fields__)
        values = {key: value for key, value in raw.items() if key in allowed}
        config = cls(**values)
        config.validate()
        return config

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CONFIG_PATH) -> "MonitorConfig":
        config_path = Path(path)
        if not config_path.exists():
            config = cls()
            config.save(config_path)
            return config
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MonitorConfigError("无法读取监控配置文件") from exc
        if not isinstance(raw, dict):
            raise MonitorConfigError("监控配置必须是 JSON 对象")
        return cls.from_dict(raw)

    def save(self, path: Path | str = DEFAULT_CONFIG_PATH) -> None:
        self.validate()
        config_path = Path(path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = config_path.with_suffix(config_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, config_path)
