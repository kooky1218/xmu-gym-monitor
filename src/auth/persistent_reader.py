from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Iterator

from src.api.stadium_reader import (
    AuthenticationRequiredError,
    StadiumReader,
    TransportError,
)
from src.auth.login import write_auth_state
from src.auth.persistent_browser import (
    BrowserRequestSession,
    LOGIN_URL,
    PersistentBrowserError,
    open_persistent_browser,
)


class BrowserAuthLabel:
    @property
    def label(self) -> str:
        return "统一身份认证（持久浏览器）"


class PersistentBrowserStadiumReader:
    """StadiumReader facade that keeps authentication inside a browser profile."""

    def __init__(self, *, cache=None, profile_dir=None) -> None:
        self.cache = cache
        self.profile_dir = profile_dir
        self.auth_adapter = BrowserAuthLabel()

    @contextlib.contextmanager
    def _browser(self) -> Iterator[BrowserRequestSession]:
        kwargs = {"headless": True}
        if self.profile_dir is not None:
            kwargs["profile_dir"] = self.profile_dir
        try:
            with open_persistent_browser(**kwargs) as browser:
                yield browser
        except PersistentBrowserError as exc:
            diagnostics = {
                "data_source": "unknown",
                "fetched_at": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "cache_age": None,
                "http_status": None,
                "business_status": None,
                "request_success": False,
                "parse_success": False,
                "error_type": "transport_error",
            }
            raise TransportError(
                "无法使用统一认证浏览器会话，请确认登录窗口已关闭",
                diagnostics=diagnostics,
            ) from exc

    def _ensure_session(self, browser: BrowserRequestSession) -> None:
        if browser.is_logged_in():
            write_auth_state("logged_in", message="统一身份认证会话有效。")
            return

        try:
            browser.navigate(LOGIN_URL)
            browser.wait_for_timeout(3000)
        except Exception:
            pass

        if browser.is_logged_in():
            write_auth_state(
                "logged_in",
                message="统一身份认证已静默续期。",
            )
            return

        write_auth_state(
            "reauth_required",
            message="统一身份认证会话已失效，需要人工重新登录。",
        )
        raise AuthenticationRequiredError(
            "统一身份认证会话已失效，请重新登录",
            diagnostics={
                "data_source": "unknown",
                "fetched_at": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "cache_age": None,
                "http_status": None,
                "business_status": 0,
                "request_success": True,
                "parse_success": False,
                "error_type": "authentication_required",
            },
        )

    def read_gym_snapshot(self, **kwargs):
        with self._browser() as browser:
            self._ensure_session(browser)
            reader = StadiumReader(
                session=browser,
                trust_env=False,
                cache=self.cache,
            )
            return reader.read_gym_snapshot(**kwargs)

    def load_cached_snapshot(self):
        if self.cache is None:
            return None
        return self.cache.load()
