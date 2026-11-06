from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.auth.persistent_browser import (
    DETAIL_URL,
    LOGIN_URL,
    PersistentBrowserError,
    open_persistent_browser,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = PROJECT_ROOT / "data" / "auth_state.json"


def write_auth_state(
    status: str,
    *,
    message: str,
    checked_at: datetime | None = None,
) -> None:
    current = checked_at or datetime.now().astimezone()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "status": status,
                "message": message,
                "checked_at": current.isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, STATE_PATH)


def read_auth_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def interactive_unified_login(timeout_minutes: int = 15) -> int:
    write_auth_state(
        "pending",
        message="请在弹出的浏览器中完成统一身份认证和人工验证码。",
    )
    deadline = time.monotonic() + timeout_minutes * 60
    try:
        with open_persistent_browser(headless=False) as browser:
            browser.navigate(LOGIN_URL)
            while time.monotonic() < deadline:
                if browser.is_logged_in():
                    browser.navigate(DETAIL_URL)
                    write_auth_state(
                        "logged_in",
                        message="统一身份认证会话已建立，场馆接口返回成功。",
                    )
                    browser.wait_for_timeout(2000)
                    return 0
                try:
                    browser.wait_for_timeout(2500)
                except Exception:
                    time.sleep(2.5)
    except PersistentBrowserError as exc:
        write_auth_state("failed", message=str(exc))
        return 5
    except Exception as exc:
        write_auth_state(
            "failed",
            message=f"登录窗口异常：{exc.__class__.__name__}",
        )
        return 5
    write_auth_state(
        "reauth_required",
        message=(
            "在限定时间内未检测到有效场馆会话。"
            "请重新打开统一身份认证窗口，并确认登录后能进入场馆页面。"
        ),
    )
    return 2


def check_persistent_session() -> tuple[bool, str]:
    try:
        with open_persistent_browser(headless=True) as browser:
            valid = browser.is_logged_in()
    except PersistentBrowserError as exc:
        write_auth_state("failed", message=str(exc))
        return False, str(exc)
    if valid:
        write_auth_state("logged_in", message="持久浏览器登录会话有效。")
        return True, "持久浏览器登录会话有效。"
    write_auth_state(
        "reauth_required",
        message="持久浏览器登录会话已失效，需要人工重新登录。",
    )
    return False, "持久浏览器登录会话已失效，需要人工重新登录。"
