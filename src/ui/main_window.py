from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.api.cache import CacheError
from src.api.stadium_reader import StadiumReader, StadiumReaderError
from src.monitor.config import MonitorConfig, MonitorConfigError
from src.ui.monitor_settings import MonitorSettingsDialog


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRAY_ICON_PATH = PROJECT_ROOT / "assets" / "gym-monitor-round.ico"


class QtLogHandler(logging.Handler, QObject):
    message_ready = Signal(str)

    def __init__(self) -> None:
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.message_ready.emit(self.format(record))
        except Exception:
            self.handleError(record)


class RefreshWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, reader: StadiumReader) -> None:
        super().__init__()
        self.reader = reader

    @Slot()
    def run(self) -> None:
        try:
            snapshot = self.reader.read_gym_snapshot()
        except StadiumReaderError as exc:
            self.failed.emit(
                {
                    "message": str(exc),
                    "meta": exc.diagnostics,
                }
            )
        except Exception:
            logging.getLogger(__name__).exception("Unexpected UI worker error")
            self.failed.emit(
                {
                    "message": "读取失败：发生未预期异常，请查看日志",
                    "meta": {
                        "data_source": "unknown",
                        "fetched_at": None,
                        "cache_age": None,
                        "http_status": None,
                        "business_status": None,
                        "request_success": False,
                        "parse_success": False,
                        "error_type": "unexpected_error",
                    },
                }
            )
        else:
            self.succeeded.emit(snapshot)
        finally:
            self.finished.emit()


class LogDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("运行日志")
        self.resize(860, 520)
        layout = QVBoxLayout(self)
        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

    def append(self, message: str) -> None:
        self.output.appendPlainText(message)


class MainWindow(QMainWindow):
    COLUMNS = (
        "日期",
        "星期",
        "时间段",
        "场地",
        "个人容量",
        "已选人数",
        "剩余名额",
        "开放状态",
        "说明",
    )

    def __init__(self, reader: StadiumReader) -> None:
        super().__init__()
        self.reader = reader
        self.thread: QThread | None = None
        self.worker: RefreshWorker | None = None
        self._log_lines: list[str] = []
        self.current_snapshot: dict[str, Any] | None = None
        self.monitor_settings_dialog: MonitorSettingsDialog | None = None
        self._auto_refresh_interval_minutes = 5
        self._allow_quit = False
        self._tray_notice_shown = False
        self.tray_icon: QSystemTrayIcon | None = None

        self.setWindowTitle("厦大体育健身房空位监控")
        if TRAY_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(TRAY_ICON_PATH)))
        self.resize(1120, 720)
        self._build_ui()
        self._install_log_handler()
        self._set_auth_banner(
            "请保持 Windows 微信运行并让“厦大体育”停留在已登录状态。"
            "程序只读取可见页面，不提取 Cookie 或绕过登录。",
            kind="info",
        )
        self._configure_auto_refresh()
        self._setup_tray_icon()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("翔安校区爱秋体育馆健身房", central)
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        root.addWidget(title)

        self.auth_banner = QLabel(
            "正在检查小程序登录状态。",
            central,
        )
        self.auth_banner.setWordWrap(True)
        self.auth_banner.setStyleSheet(
            "padding: 8px; background: #fff7e6; color: #7a4d00;"
            "border: 1px solid #f1d39b;"
        )
        root.addWidget(self.auth_banner)

        summary = QWidget(central)
        summary_layout = QFormLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setHorizontalSpacing(18)
        summary_layout.setVerticalSpacing(8)

        self.campus_value = QLabel("-", summary)
        self.venue_value = QLabel("-", summary)
        self.result_value = QLabel("尚未读取", summary)
        self.updated_value = QLabel("-", summary)
        self.source_value = QLabel("-", summary)
        self.cache_age_value = QLabel("-", summary)
        self.http_status_value = QLabel("-", summary)
        self.auth_value = QLabel(self.reader.auth_adapter.label, summary)

        summary_layout.addRow("校区", self.campus_value)
        summary_layout.addRow("场馆", self.venue_value)
        summary_layout.addRow("读取状态", self.result_value)
        summary_layout.addRow("最近更新时间", self.updated_value)
        summary_layout.addRow("数据来源", self.source_value)
        summary_layout.addRow("缓存年龄", self.cache_age_value)
        summary_layout.addRow("HTTP / 业务状态", self.http_status_value)
        summary_layout.addRow("认证方式", self.auth_value)
        root.addWidget(summary)

        controls = QHBoxLayout()
        self.refresh_button = QPushButton("刷新数据", central)
        self.refresh_button.setObjectName("refreshButton")
        self.refresh_button.clicked.connect(self.refresh)
        self.logs_button = QPushButton("查看日志", central)
        self.logs_button.clicked.connect(self.show_logs)
        self.auto_refresh_label = QLabel("自动刷新：每 5 分钟", central)
        self.auto_refresh_label.setObjectName("autoRefreshLabel")
        self.monitor_settings_button = QPushButton("监控设置", central)
        self.monitor_settings_button.clicked.connect(
            self.show_monitor_settings
        )
        self.auth_info_button = QPushButton("认证说明", central)
        self.auth_info_button.clicked.connect(self.show_auth_info)
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.monitor_settings_button)
        controls.addWidget(self.auto_refresh_label)
        controls.addWidget(self.auth_info_button)
        controls.addWidget(self.logs_button)
        controls.addStretch(1)
        root.addLayout(controls)

        self.table = QTableWidget(0, len(self.COLUMNS), central)
        self.table.setObjectName("scheduleTable")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.setCentralWidget(central)

    def _install_log_handler(self) -> None:
        self.log_dialog = LogDialog(self)
        self.log_handler = QtLogHandler()
        self.log_handler.message_ready.connect(self._remember_log)
        logging.getLogger().addHandler(self.log_handler)
        self.destroyed.connect(self._remove_log_handler)

    @Slot(str)
    def _remember_log(self, message: str) -> None:
        self._log_lines.append(message)
        if len(self._log_lines) > 2000:
            self._log_lines = self._log_lines[-2000:]
        self.log_dialog.append(message)

    @Slot()
    def _remove_log_handler(self) -> None:
        logging.getLogger().removeHandler(self.log_handler)

    @Slot()
    def show_logs(self) -> None:
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_dialog.activateWindow()

    @Slot()
    def show_auth_info(self) -> None:
        QMessageBox.information(
            self,
            "小程序读取说明",
            (
                "读取来源是 Windows 微信里的“厦大体育”小程序，"
                "不是独立浏览器登录。\n\n"
                "使用条件：\n"
                "1. Windows 微信保持运行并已登录。\n"
                "2. 小程序保持有效登录，不要关闭小程序窗口。\n"
                "3. 程序只通过 Windows UI Automation 读取页面文字。\n"
                "4. 不读取或重放微信 Cookie、Token、密码。\n"
                "5. 不处理验证码，不点击确认预约或提交订单。\n\n"
                "首页或场馆列表打开时，程序会只读导航到"
                "“翔安校区健身房”。如果登录失效，会明确报错并停止通知，"
                "不会把历史缓存伪装成实时结果。"
            ),
        )

    @Slot()
    def show_monitor_settings(self) -> None:
        if self.monitor_settings_dialog is None:
            self.monitor_settings_dialog = MonitorSettingsDialog(
                snapshot=self.current_snapshot,
                parent=self,
            )
        else:
            self.monitor_settings_dialog.set_snapshot(self.current_snapshot)
            self.monitor_settings_dialog.refresh_status()
        self.monitor_settings_dialog.show()
        self.monitor_settings_dialog.raise_()
        self.monitor_settings_dialog.activateWindow()

    @Slot()
    def refresh(self) -> None:
        if self.thread is not None:
            return

        self.refresh_button.setEnabled(False)
        self.result_value.setText("正在读取...")
        self.result_value.setStyleSheet("color: #8a5a00;")
        self.source_value.setText("等待服务器响应")
        self.cache_age_value.setText("-")
        self.http_status_value.setText("-")
        logging.getLogger(__name__).info("开始手动刷新健身房数据")

        self.thread = QThread(self)
        self.worker = RefreshWorker(self.reader)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self._handle_success)
        self.worker.failed.connect(self._handle_failure)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._refresh_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _configure_auto_refresh(self) -> None:
        try:
            config = MonitorConfig.load()
        except MonitorConfigError:
            config = MonitorConfig()
        self._auto_refresh_interval_minutes = max(
            config.check_interval_minutes,
            5,
        )
        interval_ms = self._auto_refresh_interval_minutes * 60 * 1000
        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.setInterval(interval_ms)
        self.auto_refresh_timer.timeout.connect(self._auto_refresh)
        self.auto_refresh_timer.start()
        self.auto_refresh_label.setText(
            f"自动刷新：每 {self._auto_refresh_interval_minutes} 分钟"
        )
        QTimer.singleShot(1200, self._auto_refresh)

    @Slot()
    def _auto_refresh(self) -> None:
        tray_active = (
            self.tray_icon is not None
            and self.tray_icon.isVisible()
        )
        if (self.isVisible() or tray_active) and self.thread is None:
            logging.getLogger(__name__).info("开始自动刷新健身房数据")
            self.refresh()

    def _setup_tray_icon(self) -> None:
        app = QApplication.instance()
        if app is None or app.platformName().lower() == "offscreen":
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon = (
            QIcon(str(TRAY_ICON_PATH))
            if TRAY_ICON_PATH.exists()
            else self.windowIcon()
        )
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("厦大体育健身房空位监控")

        menu = QMenu(self)
        open_action = QAction("打开监控", self)
        open_action.triggered.connect(self._restore_from_tray)
        refresh_action = QAction("立即刷新", self)
        refresh_action.triggered.connect(self.refresh)
        exit_action = QAction("退出程序", self)
        exit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(open_action)
        menu.addAction(refresh_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self.tray_icon = tray
        app.setQuitOnLastWindowClosed(False)

    @Slot()
    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @Slot()
    def _quit_from_tray(self) -> None:
        self._allow_quit = True
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_tray_activated(
        self,
        reason: QSystemTrayIcon.ActivationReason,
    ) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_from_tray()

    @Slot()
    def _minimize_to_tray(self) -> None:
        if self.tray_icon is None or not self.tray_icon.isVisible():
            self.showMinimized()
            return
        self.log_dialog.hide()
        if self.monitor_settings_dialog is not None:
            self.monitor_settings_dialog.hide()
        self.hide()
        if not self._tray_notice_shown:
            self.tray_icon.showMessage(
                "厦大健身房空位监控",
                "程序已最小化到右下角托盘，监控仍在运行。",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            self._tray_notice_shown = True

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.tray_icon is not None
        ):
            QTimer.singleShot(0, self._minimize_to_tray)

    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            not self._allow_quit
            and self.tray_icon is not None
            and self.tray_icon.isVisible()
        ):
            event.ignore()
            self._minimize_to_tray()
            return
        super().closeEvent(event)

    @Slot()
    def _refresh_finished(self) -> None:
        self.thread = None
        self.worker = None
        self.refresh_button.setEnabled(True)

    @Slot(object)
    def _handle_success(self, snapshot: dict[str, Any]) -> None:
        self.current_snapshot = snapshot
        self._render_snapshot(
            snapshot,
            result_text="读取成功（小程序实时页面）",
            result_color="#176b3a",
            cache_mode=False,
        )
        self._set_auth_banner(
            "小程序页面读取成功，登录态有效。"
            "后台监控会继续按设定间隔只读检查。",
            kind="success",
        )
        logging.getLogger(__name__).info(
            "健身房实时数据读取成功，共 %d 个时段",
            len(snapshot.get("intervals", {}).get("slots", [])),
        )

    def _render_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        result_text: str,
        result_color: str,
        cache_mode: bool,
    ) -> None:
        self.current_snapshot = snapshot
        if self.monitor_settings_dialog is not None:
            self.monitor_settings_dialog.set_snapshot(snapshot)
        meta = snapshot.get("meta") or {}
        intervals = snapshot.get("intervals", {})
        slots = intervals.get("slots", [])

        self.campus_value.setText(snapshot.get("campus") or "-")
        self.venue_value.setText(
            snapshot.get("venue", {}).get("name") or "-"
        )
        self.result_value.setText(result_text)
        self.result_value.setStyleSheet(
            f"color: {result_color}; font-weight: 600;"
        )
        fetched_at = meta.get("fetched_at") or snapshot.get("fetched_at") or "-"
        self.updated_value.setText(str(fetched_at))
        source = meta.get("data_source") or "unknown"
        source_text = {
            "network_live": "实时网络（network_live）",
            "mini_program_live": "小程序实时页面（mini_program_live）",
            "cache": "历史缓存（cache）",
            "mock": "模拟数据（mock）",
            "unknown": "未知（unknown）",
        }.get(source, str(source))
        self.source_value.setText(source_text)
        cache_age = meta.get("cache_age")
        self.cache_age_value.setText(
            self._format_cache_age(cache_age)
            if cache_age is not None
            else "-"
        )
        if source == "mini_program_live":
            self.http_status_value.setText(
                f"页面 {meta.get('page_kind', '-')}"
                f" / UI {meta.get('ui_source', 'desktop_uia')}"
            )
        else:
            self.http_status_value.setText(
                f"HTTP {meta.get('http_status', '-')}"
                f" / 业务 {meta.get('business_status', '-')}"
            )

        if cache_mode:
            self.table.setStyleSheet(
                "QTableWidget { background-color: #fff7e6; }"
            )
        else:
            self.table.setStyleSheet("")

        self.table.clearSpans()
        self.table.setRowCount(len(slots))
        if not slots:
            self.table.setRowCount(1)
            item = QTableWidgetItem("当前响应中没有可展示的预约时段")
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, len(self.COLUMNS))
            logging.getLogger(__name__).info("数据快照中没有可展示的预约时段")
            return

        for row_index, slot in enumerate(slots):
            values = (
                slot.get("date"),
                slot.get("week_name") or slot.get("week"),
                slot.get("time_range"),
                slot.get("area_name"),
                slot.get("personal_capacity"),
                slot.get("selected"),
                slot.get("remaining"),
                slot.get("status_text"),
                slot.get("lock_reason"),
            )
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(
                    "" if value is None else str(value)
                )
                if column_index == 7:
                    if slot.get("is_open"):
                        item.setForeground(QColor("#176b3a"))
                    else:
                        item.setForeground(QColor("#8b1e1e"))
                self.table.setItem(row_index, column_index, item)

    @Slot(object)
    def _handle_failure(self, failure: dict[str, Any]) -> None:
        message = str(failure.get("message") or "读取失败")
        meta = failure.get("meta") or {}
        self.result_value.setText("实时读取失败")
        self.result_value.setStyleSheet(
            "color: #8b1e1e; font-weight: 600;"
        )
        self.source_value.setText("未知（unknown）")
        self.cache_age_value.setText("-")
        self.http_status_value.setText(
            str(meta.get("error_type") or "读取失败")
        )

        try:
            cached = self.reader.load_cached_snapshot()
        except CacheError:
            cached = None
            logging.getLogger(__name__).warning("历史缓存读取失败")
        if cached is not None:
            self._render_snapshot(
                cached.snapshot,
                result_text="实时读取失败，正在显示历史缓存",
                result_color="#8a5a00",
                cache_mode=True,
            )
            detail_message = (
                f"{message}\n\n历史数据时间："
                f"{cached.snapshot.get('meta', {}).get('fetched_at', '-')}\n"
                f"缓存年龄：{self._format_cache_age(cached.age_seconds)}"
            )
        else:
            self.table.clearSpans()
            self.table.setRowCount(1)
            self.table.setItem(
                0,
                0,
                QTableWidgetItem("实时读取失败，且没有可用的历史缓存"),
            )
            self.table.setSpan(0, 0, 1, len(self.COLUMNS))
            self.table.setStyleSheet("")
            self.campus_value.setText("-")
            self.venue_value.setText("-")
            self.updated_value.setText("-")
            detail_message = message

        logging.getLogger(__name__).warning(
            "健身房数据读取失败：%s；data_source=%s；cache_age=%s",
            message,
            meta.get("data_source"),
            meta.get("cache_age"),
        )
        if meta.get("error_type") == "authentication_required":
            detail_message = (
                f"{detail_message}\n\n"
                "请在 Windows 微信中打开“厦大体育”并重新登录小程序。"
                "程序不会读取 Cookie、保存密码或绕过登录。"
            )
            self._set_auth_banner(
                "小程序登录态已失效，自动监控已停止发送空位通知。"
                "请手工重新登录小程序。",
                kind="error",
            )
            QMessageBox.warning(self, "需要登录认证", detail_message)
        else:
            self._set_auth_banner(
                "小程序读取失败。请确认 Windows 微信和小程序窗口仍在运行，"
                "然后重新刷新。",
                kind="error",
            )
            QMessageBox.warning(self, "读取失败", detail_message)

    @staticmethod
    def _format_cache_age(age_seconds: Any) -> str:
        try:
            seconds = max(int(age_seconds), 0)
        except (TypeError, ValueError):
            return "-"
        if seconds < 60:
            return f"{seconds} 秒"
        if seconds < 3600:
            return f"{seconds // 60} 分钟"
        if seconds < 86400:
            return f"{seconds // 3600} 小时"
        return f"{seconds // 86400} 天"

    def _set_auth_banner(self, text: str, *, kind: str) -> None:
        if kind == "success":
            style = (
                "padding: 8px; background: #eef9f2; color: #176b3a;"
                "border: 1px solid #b9e2c7;"
            )
        elif kind == "info":
            style = (
                "padding: 8px; background: #eef6ff; color: #145a96;"
                "border: 1px solid #bdd8f2;"
            )
        else:
            style = (
                "padding: 8px; background: #fff1f0; color: #8b1e1e;"
                "border: 1px solid #efc1bd;"
            )
        if self.auth_banner.text() != text:
            self.auth_banner.setText(text)
            self.auth_banner.setStyleSheet(style)
