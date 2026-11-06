from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests


LOGGER = logging.getLogger(__name__)


class BarkNotificationError(Exception):
    """Base class for Bark delivery failures."""


class BarkConfigurationError(BarkNotificationError):
    """Raised for invalid local Bark settings."""


@dataclass(frozen=True)
class BarkNotificationResult:
    success: bool
    status_code: int | None
    attempts: int
    provider_message_id: str | None = None
    error_type: str | None = None


class BarkNotifier:
    """Send iOS notifications through the official Bark V2 /push API."""

    def __init__(
        self,
        *,
        service_url: str,
        device_key: str,
        timeout: float = 10.0,
        max_retries: int = 2,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 30.0,
        session: requests.Session | None = None,
        trust_env: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not service_url.startswith(("https://", "http://")):
            raise BarkConfigurationError("Bark 服务地址必须使用 HTTP(S)")
        if not device_key.strip():
            raise BarkConfigurationError("Bark Key 不能为空")
        self.service_url = service_url.rstrip("/")
        self.device_key = device_key.strip()
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.retry_base_seconds = max(0.0, retry_base_seconds)
        self.retry_max_seconds = max(0.0, retry_max_seconds)
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = trust_env
        self.sleep = sleep
        self._recent_messages: dict[str, float] = {}

    def send(
        self,
        *,
        title: str,
        body: str,
        url: str | None = None,
        group: str = "厦大体育空位监控",
        dedup_seconds: float = 60.0,
    ) -> BarkNotificationResult:
        if not title.strip() or not body.strip():
            raise BarkConfigurationError("通知标题和正文不能为空")
        if url and not url.startswith(("https://", "http://")):
            raise BarkConfigurationError("通知跳转 URL 必须使用 HTTP(S)")
        if dedup_seconds > 0:
            signature = self._signature(title, body, url)
            now_monotonic = time.monotonic()
            last_sent = self._recent_messages.get(signature)
            if (
                last_sent is not None
                and now_monotonic - last_sent < dedup_seconds
            ):
                LOGGER.info("Bark 通知内容在短时间去重窗口内，已跳过")
                return BarkNotificationResult(
                    success=True,
                    status_code=None,
                    attempts=0,
                    provider_message_id="deduplicated",
                )

        payload: dict[str, Any] = {
            "device_key": self.device_key,
            "title": title,
            "body": body,
            "group": group,
        }
        if url:
            payload["url"] = url
        endpoint = (
            self.service_url
            if self.service_url.endswith("/push")
            else self.service_url + "/push"
        )
        last_status: int | None = None
        last_error = "network_error"

        for attempt in range(1, self.max_retries + 2):
            try:
                response = self.session.post(
                    endpoint,
                    json=payload,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                last_status = response.status_code
                if response.status_code == 429:
                    last_error = "rate_limited"
                    if attempt <= self.max_retries:
                        self.sleep(
                            self._retry_delay(
                                attempt,
                                response.headers.get("Retry-After"),
                            )
                        )
                        continue
                    return BarkNotificationResult(
                        success=False,
                        status_code=response.status_code,
                        attempts=attempt,
                        error_type=last_error,
                    )
                elif response.status_code >= 500:
                    last_error = "server_error"
                    if attempt <= self.max_retries:
                        self.sleep(self._retry_delay(attempt))
                        continue
                    return BarkNotificationResult(
                        success=False,
                        status_code=response.status_code,
                        attempts=attempt,
                        error_type=last_error,
                    )
                elif response.status_code >= 400:
                    last_error = "client_error"
                    return BarkNotificationResult(
                        success=False,
                        status_code=response.status_code,
                        attempts=attempt,
                        error_type=last_error,
                    )

                response.raise_for_status()
                response_json: dict[str, Any] = {}
                try:
                    parsed = response.json()
                    if isinstance(parsed, dict):
                        response_json = parsed
                except ValueError:
                    pass
                provider_code = response_json.get("code")
                if provider_code not in (None, 200, "200"):
                    last_error = "provider_error"
                    return BarkNotificationResult(
                        success=False,
                        status_code=response.status_code,
                        attempts=attempt,
                        error_type=last_error,
                    )
                if dedup_seconds > 0:
                    self._recent_messages[signature] = time.monotonic()
                LOGGER.info("Bark 通知发送成功")
                message_id = response_json.get(
                    "id",
                    response_json.get("message_id"),
                )
                return BarkNotificationResult(
                    success=True,
                    status_code=response.status_code,
                    attempts=attempt,
                    provider_message_id=(
                        str(message_id) if message_id is not None else None
                    ),
                )
            except requests.RequestException:
                last_error = "network_error"
                if attempt <= self.max_retries:
                    self.sleep(self._retry_delay(attempt))
                    continue

        LOGGER.warning("Bark 通知发送失败：%s", last_error)
        return BarkNotificationResult(
            success=False,
            status_code=last_status,
            attempts=self.max_retries + 1,
            error_type=last_error,
        )

    def send_test(self, *, url: str | None = None) -> BarkNotificationResult:
        return self.send(
            title="厦大体育空位监控测试",
            body="如果你收到这条通知，说明 Bark 已配置成功。",
            url=url,
            dedup_seconds=0,
        )

    def _retry_delay(
        self,
        attempt: int,
        retry_after: str | None = None,
    ) -> float:
        if retry_after:
            try:
                return min(
                    max(float(retry_after), 0.0),
                    self.retry_max_seconds,
                )
            except ValueError:
                pass
        delay = self.retry_base_seconds * (2 ** max(attempt - 1, 0))
        return min(delay, self.retry_max_seconds)

    @staticmethod
    def _signature(title: str, body: str, url: str | None) -> str:
        source = f"{title}\0{body}\0{url or ''}"
        return hashlib.sha256(source.encode("utf-8")).hexdigest()
