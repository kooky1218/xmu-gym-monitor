from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

from src.api.cache import SnapshotCache
from src.api.stadium_reader import (
    AuthenticationRequiredError,
    StadiumReaderError,
)
from src.monitor.availability_monitor import AvailabilityMonitor
from src.monitor.change_detector import (
    ChangeDetector,
    DEFAULT_DATABASE_PATH,
    MonitorStateDatabase,
)
from src.monitor.config import (
    DEFAULT_CONFIG_PATH,
    MonitorConfig,
    MonitorConfigError,
)
from src.monitor.miniprogram_reader import MiniProgramStadiumReader
from src.notification.bark_notifier import (
    BarkConfigurationError,
    BarkNotificationResult,
)
from src.notification.bark_notifier import BarkNotifier
from src.notification.credential_store import (
    BarkCredentialStore,
    CredentialStoreError,
)
from src.notification.messages import (
    build_availability_notification,
    build_system_error_notification,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK_PATH = PROJECT_ROOT / "data" / "monitor.lock"
LOG_PATH = PROJECT_ROOT / "logs" / "monitor.log"
LOGGER = logging.getLogger(__name__)


class NotifierLike(Protocol):
    def send(
        self,
        *,
        title: str,
        body: str,
        url: str | None = None,
        group: str = ...,
        dedup_seconds: float = ...,
    ) -> BarkNotificationResult:
        ...


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    status: str
    error_type: str | None = None
    message: str | None = None
    data_source: str | None = None
    matched_count: int = 0
    notification_count: int = 0


class InstanceAlreadyRunning(Exception):
    """Raised when another monitor process owns the lock."""


@contextlib.contextmanager
def single_instance_lock(path: Path | str = DEFAULT_LOCK_PATH) -> Iterator[None]:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise InstanceAlreadyRunning() from exc
            acquired = True
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise InstanceAlreadyRunning() from exc
            acquired = True
        yield
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        else:
            handle.close()


def configure_worker_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == LOG_PATH.resolve()
        for handler in root.handlers
    ):
        return
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


class MonitorRunner:
    def __init__(
        self,
        *,
        config: MonitorConfig,
        database: MonitorStateDatabase,
        reader: Any,
        credential_store: Any | None = None,
        notifier: NotifierLike | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.database = database
        self.reader = reader
        self.credential_store = credential_store or BarkCredentialStore()
        self.notifier = notifier
        self.sleeper = sleeper
        self.detector = ChangeDetector(
            database,
            cooldown_minutes=config.notification_cooldown_minutes,
        )

    def run_once(self) -> RunResult:
        started = datetime.now().astimezone()
        if not self.config.enabled:
            return self._record(
                RunResult(
                    exit_code=0,
                    status="disabled",
                    message="监控已关闭",
                ),
                started,
            )

        monitor = AvailabilityMonitor(self.reader, self.config)
        data_source = None
        matched_count = 0
        parse_success = False
        try:
            result = self._read_with_retry(monitor)
            data_source = result.data_source
            matched_count = len(result.slots)
            parse_success = True
        except AuthenticationRequiredError as exc:
            error = RunResult(
                exit_code=2,
                status="AUTH_REQUIRED",
                error_type="AUTH_REQUIRED",
                message=str(exc),
            )
            self._send_system_alert_if_enabled(error)
            return self._record(error, started)
        except StadiumReaderError as exc:
            error_type = (exc.diagnostics or {}).get(
                "error_type",
                exc.__class__.__name__,
            )
            error = RunResult(
                exit_code=5,
                status="READ_FAILED",
                error_type=str(error_type),
                message=str(exc),
                data_source=(exc.diagnostics or {}).get("data_source"),
            )
            self._send_system_alert_if_enabled(error)
            return self._record(error, started)
        except Exception:
            LOGGER.exception("监控读取发生未预期异常")
            error = RunResult(
                exit_code=5,
                status="UNEXPECTED_ERROR",
                error_type="unexpected_error",
                message="监控读取发生未预期异常",
            )
            self._send_system_alert_if_enabled(error)
            return self._record(error, started)

        if result.test_mode:
            LOGGER.info(
                "数据来源 %s 处于测试模式，不发送真实空位通知",
                result.data_source,
            )
            return self._record(
                RunResult(
                    exit_code=0,
                    status="TEST_MODE",
                    message="非实时数据仅用于展示和测试",
                    data_source=data_source,
                    matched_count=matched_count,
                ),
                started,
            )

        pending = self.detector.detect(result)
        if not pending:
            return self._record(
                RunResult(
                    exit_code=0,
                    status="NO_NEW_AVAILABILITY",
                    data_source=data_source,
                    matched_count=matched_count,
                ),
                started,
            )

        notifier = self._build_notifier()
        if notifier is None:
            for item in pending:
                self.detector.mark_failed(
                    item,
                    title="Bark Key 未配置",
                    body="",
                    attempted_at=datetime.now().astimezone(),
                    error_type="credential_missing",
                )
            return self._record(
                RunResult(
                    exit_code=6,
                    status="NOTIFICATION_NOT_CONFIGURED",
                    error_type="credential_missing",
                    message="发现空位但未配置 Bark Key",
                    data_source=data_source,
                    matched_count=matched_count,
                ),
                started,
            )

        success_count = 0
        for item in pending:
            now = datetime.now().astimezone()
            title, body, jump_url = build_availability_notification(
                item.slot,
                self.config,
                discovered_at=now,
            )
            try:
                sent = notifier.send(
                    title=title,
                    body=body,
                    url=jump_url,
                    dedup_seconds=60,
                )
            except Exception:
                LOGGER.exception("Bark 通知调用异常")
                self.detector.mark_failed(
                    item,
                    title=title,
                    body=body,
                    attempted_at=now,
                    error_type="notifier_exception",
                )
                continue
            if sent.success:
                success_count += 1
                self.detector.mark_sent(
                    item,
                    title=title,
                    body=body,
                    sent_at=now,
                    provider_message_id=sent.provider_message_id,
                )
            else:
                self.detector.mark_failed(
                    item,
                    title=title,
                    body=body,
                    attempted_at=now,
                    error_type=sent.error_type or "send_failed",
                )

        if success_count != len(pending):
            return self._record(
                RunResult(
                    exit_code=6,
                    status="NOTIFICATION_PARTIAL_FAILURE",
                    error_type="notification_failed",
                    message=(
                        f"发现 {len(pending)} 个空位，成功推送 "
                        f"{success_count} 条"
                    ),
                    data_source=data_source,
                    matched_count=matched_count,
                    notification_count=success_count,
                ),
                started,
            )
        return self._record(
            RunResult(
                exit_code=0,
                status="NOTIFIED",
                data_source=data_source,
                matched_count=matched_count,
                notification_count=success_count,
            ),
            started,
        )

    def _read_with_retry(self, monitor: AvailabilityMonitor):
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                return monitor.read()
            except AuthenticationRequiredError:
                raise
            except StadiumReaderError as exc:
                if attempt >= max_attempts or not self._retryable(exc):
                    raise
                diagnostics = exc.diagnostics or {}
                http_status = diagnostics.get("http_status")
                delay = self._retry_delay(attempt, http_status)
                LOGGER.warning(
                    "监控读取失败，%s 秒后进行第 %d 次重试",
                    delay,
                    attempt,
                )
                self.sleeper(delay)

    @staticmethod
    def _retryable(exc: StadiumReaderError) -> bool:
        diagnostics = exc.diagnostics or {}
        status = diagnostics.get("http_status")
        error_type = diagnostics.get("error_type")
        if error_type == "transport_error":
            return True
        return status in (429, 500, 502, 503, 504)

    @staticmethod
    def _retry_delay(attempt: int, status: int | None) -> float:
        if status == 429:
            return 15.0 * (2 ** (attempt - 1))
        return 2.0 * (2 ** (attempt - 1))

    def _build_notifier(self) -> BarkNotifier | None:
        if self.notifier is not None:
            return self.notifier  # type: ignore[return-value]
        try:
            key = self.credential_store.get_key()
        except CredentialStoreError:
            LOGGER.warning("无法从 Windows 凭据管理器读取 Bark Key")
            return None
        if not key:
            return None
        try:
            return BarkNotifier(
                service_url=self.config.bark_service_url,
                device_key=key,
            )
        except BarkConfigurationError:
            LOGGER.warning("Bark 配置无效")
            return None

    def _send_system_alert_if_enabled(self, result: RunResult) -> None:
        if not self.config.notify_on_system_error:
            return
        notifier = self._build_notifier()
        if notifier is None:
            return
        now = datetime.now().astimezone()
        if not self.detector.should_send_system_alert(
            result.error_type or result.status,
            now=now,
            cooldown_minutes=self.config.system_error_cooldown_minutes,
        ):
            return
        title, body, _ = build_system_error_notification(
            error_type=result.error_type or result.status,
            message=result.message or "",
            occurred_at=now,
        )
        try:
            sent = notifier.send(
                title=title,
                body=body,
                dedup_seconds=0,
            )
        except Exception:
            LOGGER.exception("系统异常 Bark 通知失败")
            self.detector.mark_system_alert_result(
                result.error_type or result.status,
                success=False,
                at=now,
                error_type="notifier_exception",
            )
            return
        self.detector.mark_system_alert_result(
            result.error_type or result.status,
            success=sent.success,
            at=now,
            error_type=sent.error_type,
        )

    def _record(self, result: RunResult, started: datetime) -> RunResult:
        finished = datetime.now().astimezone()
        try:
            self.detector.update_run_outcome(
                started_at=started,
                finished_at=finished,
                data_source=result.data_source,
                read_success=result.status not in {
                    "READ_FAILED",
                    "AUTH_REQUIRED",
                    "UNEXPECTED_ERROR",
                },
                parse_success=result.status in {
                    "NO_NEW_AVAILABILITY",
                    "NOTIFIED",
                    "TEST_MODE",
                    "NOTIFICATION_NOT_CONFIGURED",
                    "NOTIFICATION_PARTIAL_FAILURE",
                },
                matched_count=result.matched_count,
                notification_count=result.notification_count,
                exit_code=result.exit_code,
                error_type=result.error_type,
                error_message=result.message,
            )
        except Exception:
            LOGGER.exception("写入监控运行记录失败")
        LOGGER.info(
            "监控任务结束 status=%s exit_code=%s matched=%d notified=%d",
            result.status,
            result.exit_code,
            result.matched_count,
            result.notification_count,
        )
        return result


def simulate_notification(
    config: MonitorConfig,
    *,
    credential_store: Any | None = None,
    notifier: NotifierLike | None = None,
) -> RunResult:
    store = credential_store or BarkCredentialStore()
    actual_notifier = notifier
    if actual_notifier is None:
        try:
            key = store.get_key()
        except CredentialStoreError as exc:
            return RunResult(6, "SIMULATION_FAILED", "credential_error", str(exc))
        if not key:
            return RunResult(
                6,
                "SIMULATION_FAILED",
                "credential_missing",
                "未配置 Bark Key",
            )
        actual_notifier = BarkNotifier(
            service_url=config.bark_service_url,
            device_key=key,
        )
    now = datetime.now().astimezone()
    body = (
        "【测试模式，不是真实空位】\n"
        f"场馆：{config.stadium_name}\n"
        f"日期：{config.target_dates[0] if config.target_dates else '2026-11-06'}\n"
        f"时段：{config.target_slots[0] if config.target_slots else '18:00-19:00'}\n"
        "剩余名额：3\n"
        f"发现时间：{now.strftime('%H:%M:%S')}"
    )
    try:
        sent = actual_notifier.send(
            title="【测试】厦大健身房空位监控",
            body=body,
            url=config.notification_jump_url or None,
            dedup_seconds=0,
        )
    except Exception as exc:
        return RunResult(
            6,
            "SIMULATION_FAILED",
            "notifier_exception",
            str(exc),
        )
    if not sent.success:
        return RunResult(
            6,
            "SIMULATION_FAILED",
            sent.error_type or "send_failed",
            "测试通知发送失败",
        )
    return RunResult(
        0,
        "SIMULATION_SENT",
        notification_count=1,
    )


def run_daemon(
    *,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    database_path: Path | str = DEFAULT_DATABASE_PATH,
    lock_path: Path | str = DEFAULT_LOCK_PATH,
    stop_event: threading.Event | None = None,
    sleeper: Callable[[float], bool | None] | None = None,
) -> int:
    """Run low-frequency checks until the process is stopped.

    The daemon owns the single-instance lock for its entire lifetime. Each
    iteration reloads configuration so GUI changes take effect without a
    process restart.
    """

    stop = stop_event or threading.Event()
    if sleeper is None:
        def wait(seconds: float) -> bool:
            return stop.wait(max(seconds, 0))
    else:
        wait = sleeper

    try:
        with single_instance_lock(lock_path):
            LOGGER.info("后台监控守护进程启动")
            while not stop.is_set():
                interval_minutes = 5
                try:
                    config = MonitorConfig.load(config_path)
                    interval_minutes = config.check_interval_minutes
                    if not config.enabled:
                        LOGGER.info("监控已关闭，后台等待下一轮配置检查")
                    else:
                        database = MonitorStateDatabase(database_path)
                        reader = MiniProgramStadiumReader(
                            cache=SnapshotCache(
                                PROJECT_ROOT
                                / "cache"
                                / "latest_snapshot.json"
                            ),
                        )
                        runner = MonitorRunner(
                            config=config,
                            database=database,
                            reader=reader,
                        )
                        runner.run_once()
                except MonitorConfigError as exc:
                    LOGGER.error("后台监控配置无效：%s", exc)
                except InstanceAlreadyRunning:
                    LOGGER.warning("已有监控实例，后台守护进程退出")
                    return 3
                except Exception:
                    LOGGER.exception("后台监控轮次发生未处理异常，将继续运行")

                should_stop = wait(max(interval_minutes, 5) * 60)
                if should_stop:
                    break
            LOGGER.info("后台监控守护进程停止")
            return 0
    except InstanceAlreadyRunning:
        LOGGER.warning("已有监控实例，后台守护进程退出")
        return 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="厦大健身房后台空位监控")
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--database", default=str(DEFAULT_DATABASE_PATH))
    parser.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--simulate-notification", action="store_true")
    parser.add_argument("--send-test-notification", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = _build_parser().parse_args(argv)
    configure_worker_logging()
    try:
        config = MonitorConfig.load(args.config)
    except MonitorConfigError as exc:
        LOGGER.error("监控配置无效：%s", exc)
        return 4

    if args.send_test_notification:
        result = simulate_notification(config)
        LOGGER.info("测试通知结果：%s", result.status)
        print(json.dumps(_result_dict(result), ensure_ascii=False))
        return result.exit_code

    if args.simulate_notification:
        result = simulate_notification(config)
        LOGGER.info("模拟通知结果：%s", result.status)
        print(json.dumps(_result_dict(result), ensure_ascii=False))
        return result.exit_code

    if args.daemon:
        return run_daemon(
            config_path=args.config,
            database_path=args.database,
            lock_path=args.lock,
        )

    if not args.run_once:
        _build_parser().print_help()
        return 0

    try:
        with single_instance_lock(args.lock):
            database = MonitorStateDatabase(args.database)
            reader = MiniProgramStadiumReader(
                cache=SnapshotCache(
                    PROJECT_ROOT / "cache" / "latest_snapshot.json"
                ),
            )
            runner = MonitorRunner(
                config=config,
                database=database,
                reader=reader,
            )
            result = runner.run_once()
            print(json.dumps(_result_dict(result), ensure_ascii=False))
            return result.exit_code
    except InstanceAlreadyRunning:
        LOGGER.warning("已有监控任务正在运行，本次跳过")
        return 3
    except Exception:
        LOGGER.exception("监控任务发生未处理异常")
        return 5


def _result_dict(result: RunResult) -> dict[str, Any]:
    return {
        "exit_code": result.exit_code,
        "status": result.status,
        "error_type": result.error_type,
        "message": result.message,
        "data_source": result.data_source,
        "matched_count": result.matched_count,
        "notification_count": result.notification_count,
    }


if __name__ == "__main__":
    raise SystemExit(main())
