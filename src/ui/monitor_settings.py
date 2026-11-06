from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.monitor.availability_monitor import AvailabilityMonitor
from src.monitor.change_detector import (
    DEFAULT_DATABASE_PATH,
    MonitorStateDatabase,
)
from src.monitor.config import (
    DEFAULT_CONFIG_PATH,
    MonitorConfig,
    MonitorConfigError,
)
from src.notification.bark_notifier import BarkNotifier
from src.notification.credential_store import (
    BarkCredentialStore,
    CredentialStoreError,
)


class BarkTestWorker(QObject):
    completed = Signal(bool, str)
    finished = Signal()

    def __init__(
        self,
        *,
        service_url: str,
        device_key: str,
        jump_url: str | None,
    ) -> None:
        super().__init__()
        self.service_url = service_url
        self.device_key = device_key
        self.jump_url = jump_url

    @Slot()
    def run(self) -> None:
        try:
            notifier = BarkNotifier(
                service_url=self.service_url,
                device_key=self.device_key,
            )
            result = notifier.send_test(url=self.jump_url)
        except Exception as exc:
            self.completed.emit(False, f"测试失败：{exc.__class__.__name__}")
        else:
            if result.success:
                self.completed.emit(True, "测试通知已发送")
            else:
                self.completed.emit(
                    False,
                    f"测试失败：{result.error_type or 'unknown'}",
                )
        finally:
            self.finished.emit()


class MonitorSettingsDialog(QDialog):
    def __init__(
        self,
        *,
        snapshot: dict[str, Any] | None = None,
        config_path: Path | str = DEFAULT_CONFIG_PATH,
        database_path: Path | str = DEFAULT_DATABASE_PATH,
        credential_store: BarkCredentialStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self.config_path = Path(config_path)
        self.database_path = Path(database_path)
        self.credential_store = credential_store
        self.test_thread: QThread | None = None
        self.test_worker: BarkTestWorker | None = None
        self.setWindowTitle("空位监控设置")
        self.resize(780, 560)
        self.setMinimumSize(640, 460)
        self._build_ui()
        self.load_config()
        self.refresh_status()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.mode_label = QLabel(self)
        self.mode_label.setWordWrap(True)
        self.mode_label.setStyleSheet(
            "padding: 8px; background: #fff7e6; color: #7a4d00;"
            "border: 1px solid #f1d39b;"
        )
        root.addWidget(self.mode_label)

        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_scope_tab(), "监测范围")
        self.tabs.addTab(self._build_notification_tab(), "Bark 通知")
        self.tabs.addTab(self._build_status_tab(), "运行状态")

        buttons = QHBoxLayout()
        self.save_button = QPushButton("保存配置", self)
        self.save_button.clicked.connect(self.save_config)
        self.close_button = QPushButton("关闭", self)
        self.close_button.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)

    def _build_scope_tab(self) -> QWidget:
        page = QWidget(self)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        venue = QGroupBox("场馆信息", content)
        venue_form = QFormLayout(venue)
        venue_form.setContentsMargins(10, 8, 10, 8)
        self.campus_value = QLabel("翔安校区", venue)
        self.stadium_value = QLabel("爱秋体育馆健身房", venue)
        venue_form.addRow("校区 / 场馆", self.campus_value)
        venue_form.addRow("", self.stadium_value)
        layout.addWidget(venue)

        columns = QHBoxLayout()
        columns.setSpacing(8)
        dates = QGroupBox("监控日期", content)
        dates_layout = QVBoxLayout(dates)
        dates_layout.setContentsMargins(8, 8, 8, 8)
        add_date_row = QHBoxLayout()
        self.date_edit = QDateEdit(QDate.currentDate(), dates)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.add_date_button = QPushButton("添加日期", dates)
        self.add_date_button.clicked.connect(self.add_date)
        self.remove_date_button = QPushButton("移除选中", dates)
        self.remove_date_button.clicked.connect(self.remove_dates)
        add_date_row.addWidget(self.date_edit, 1)
        add_date_row.addWidget(self.add_date_button)
        add_date_row.addWidget(self.remove_date_button)
        dates_layout.addLayout(add_date_row)
        dates_hint = QLabel(
            "日期列表留空时，监控小程序当前可见的全部日期。",
            dates,
        )
        dates_hint.setWordWrap(True)
        dates_layout.addWidget(dates_hint)
        self.date_list = QListWidget(dates)
        self.date_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.date_list.setMaximumHeight(120)
        dates_layout.addWidget(self.date_list)
        columns.addWidget(dates, 1)

        slots = QGroupBox("监控时段", content)
        slots_layout = QVBoxLayout(slots)
        slots_layout.setContentsMargins(8, 8, 8, 8)
        slots_hint = QLabel(
            "留空表示监控整个日期；选择时段则只匹配具体时间。",
            slots,
        )
        slots_hint.setWordWrap(True)
        slots_layout.addWidget(slots_hint)
        self.slot_list = QListWidget(slots)
        self.slot_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.slot_list.setMaximumHeight(120)
        slots_layout.addWidget(self.slot_list)
        self.reload_slots_button = QPushButton("刷新时段", slots)
        self.reload_slots_button.clicked.connect(self.reload_slot_options)
        slots_layout.addWidget(self.reload_slots_button)
        columns.addWidget(slots, 1)
        layout.addLayout(columns)

        params = QGroupBox("监控参数", content)
        form = QGridLayout(params)
        form.setContentsMargins(10, 8, 10, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        self.enabled_checkbox = QCheckBox("开启后台空位监控", params)
        self.interval_spin = QSpinBox(params)
        self.interval_spin.setRange(5, 60)
        self.interval_spin.setSuffix(" 分钟")
        self.min_remaining_spin = QSpinBox(params)
        self.min_remaining_spin.setRange(1, 999)
        self.cooldown_spin = QSpinBox(params)
        self.cooldown_spin.setRange(0, 1440)
        self.cooldown_spin.setSuffix(" 分钟")
        self.system_error_checkbox = QCheckBox("发送认证失效和读取异常提醒", params)
        form.addWidget(self.enabled_checkbox, 0, 0, 1, 2)
        form.addWidget(QLabel("检查间隔", params), 1, 0)
        form.addWidget(self.interval_spin, 1, 1)
        form.addWidget(QLabel("最少剩余名额", params), 2, 0)
        form.addWidget(self.min_remaining_spin, 2, 1)
        form.addWidget(QLabel("通知冷却", params), 3, 0)
        form.addWidget(self.cooldown_spin, 3, 1)
        form.addWidget(self.system_error_checkbox, 4, 0, 1, 2)
        layout.addWidget(params)
        layout.addStretch(1)
        return page

    def _build_notification_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        group = QGroupBox("Bark 配置", page)
        form = QFormLayout(group)
        self.bark_url_edit = QLineEdit("https://api.day.app", group)
        self.bark_key_edit = QLineEdit(group)
        self.bark_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.bark_key_edit.setPlaceholderText(
            "留空则保留 Windows 凭据管理器中的现有 Key"
        )
        self.bark_result_label = QLabel("尚未测试", group)
        self.bark_result_label.setWordWrap(True)
        self.test_bark_button = QPushButton("发送测试通知", group)
        self.test_bark_button.clicked.connect(self.test_bark)
        form.addRow("服务地址", self.bark_url_edit)
        form.addRow("设备 Key", self.bark_key_edit)
        form.addRow("", self.test_bark_button)
        form.addRow("测试结果", self.bark_result_label)
        layout.addWidget(group)
        security = QLabel(
            "Bark Key 保存在 Windows Credential Manager，不写入 JSON 配置，"
            "也不会出现在普通日志中。",
            page,
        )
        security.setWordWrap(True)
        layout.addWidget(security)
        layout.addStretch(1)
        return page

    def _build_status_tab(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        self.monitor_status = QLabel("-", page)
        self.last_check_status = QLabel("-", page)
        self.read_status = QLabel("-", page)
        self.next_check_status = QLabel("-", page)
        self.data_source_status = QLabel("-", page)
        self.matched_status = QLabel("-", page)
        self.notification_status = QLabel("-", page)
        self.error_status = QLabel("-", page)
        self.error_status.setWordWrap(True)
        form.addRow("当前监控", self.monitor_status)
        form.addRow("上次检查", self.last_check_status)
        form.addRow("下次计划检查", self.next_check_status)
        form.addRow("数据来源", self.data_source_status)
        form.addRow("读取状态", self.read_status)
        form.addRow("匹配场次", self.matched_status)
        form.addRow("累计通知", self.notification_status)
        form.addRow("最近错误", self.error_status)
        return page

    def load_config(self) -> None:
        try:
            config = MonitorConfig.load(self.config_path)
        except MonitorConfigError as exc:
            QMessageBox.warning(self, "配置读取失败", str(exc))
            config = MonitorConfig()

        self.enabled_checkbox.setChecked(config.enabled)
        self.interval_spin.setValue(config.check_interval_minutes)
        self.min_remaining_spin.setValue(config.min_remaining)
        self.cooldown_spin.setValue(config.notification_cooldown_minutes)
        self.system_error_checkbox.setChecked(config.notify_on_system_error)
        self.bark_url_edit.setText(config.bark_service_url)
        self._set_dates(config.target_dates)
        self._set_slot_options(config.target_slots)
        self._update_mode_label()

    def set_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        self.snapshot = snapshot
        self._update_mode_label()
        self.reload_slot_options()

    def _set_dates(self, values: list[str]) -> None:
        self.date_list.clear()
        for value in values:
            self.date_list.addItem(QListWidgetItem(value))

    def _set_slot_options(self, selected: list[str]) -> None:
        options: list[str] = []
        if self.snapshot:
            _, discovered = AvailabilityMonitor.discover_options(self.snapshot)
            options.extend(discovered)
        for value in selected:
            if value not in options:
                options.append(value)
        self.slot_list.clear()
        selected_set = set(selected)
        for value in sorted(options):
            item = QListWidgetItem(value)
            item.setSelected(value in selected_set)
            self.slot_list.addItem(item)

    @Slot()
    def reload_slot_options(self) -> None:
        selected = [
            self.slot_list.item(index).text()
            for index in range(self.slot_list.count())
            if self.slot_list.item(index).isSelected()
        ]
        self._set_slot_options(selected)

    @Slot()
    def add_date(self) -> None:
        value = self.date_edit.date().toString("yyyy-MM-dd")
        existing = {
            self.date_list.item(index).text()
            for index in range(self.date_list.count())
        }
        if value not in existing:
            self.date_list.addItem(QListWidgetItem(value))

    @Slot()
    def remove_dates(self) -> None:
        for item in self.date_list.selectedItems():
            self.date_list.takeItem(self.date_list.row(item))

    def _collect_config(self) -> MonitorConfig:
        dates = sorted(
            {
                self.date_list.item(index).text()
                for index in range(self.date_list.count())
            }
        )
        slots = sorted(
            {
                self.slot_list.item(index).text()
                for index in range(self.slot_list.count())
                if self.slot_list.item(index).isSelected()
            }
        )
        current = MonitorConfig.load(self.config_path)
        current.target_dates = dates
        current.target_slots = slots
        current.enabled = self.enabled_checkbox.isChecked()
        current.check_interval_minutes = self.interval_spin.value()
        current.min_remaining = self.min_remaining_spin.value()
        current.notification_cooldown_minutes = self.cooldown_spin.value()
        current.notify_on_system_error = (
            self.system_error_checkbox.isChecked()
        )
        current.bark_service_url = self.bark_url_edit.text().strip()
        current.validate()
        return current

    @Slot()
    def save_config(self) -> None:
        try:
            config = self._collect_config()
            config.save(self.config_path)
            key = self.bark_key_edit.text().strip()
            if key:
                self._get_credential_store().set_key(key)
                self.bark_key_edit.clear()
        except (MonitorConfigError, CredentialStoreError) as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.bark_result_label.setText("配置已保存")
        self._update_mode_label()
        self.refresh_status()
        logging.getLogger(__name__).info("空位监控配置已保存")

    def _get_credential_store(self) -> BarkCredentialStore:
        if self.credential_store is None:
            self.credential_store = BarkCredentialStore()
        return self.credential_store

    @Slot()
    def test_bark(self) -> None:
        if self.test_thread is not None:
            return
        try:
            key = self.bark_key_edit.text().strip()
            if not key:
                key = self._get_credential_store().get_key() or ""
        except CredentialStoreError as exc:
            self.bark_result_label.setText(str(exc))
            return
        if not key:
            self.bark_result_label.setText("请先输入 Bark Key")
            return

        config = self._collect_config()
        self.test_bark_button.setEnabled(False)
        self.bark_result_label.setText("正在发送测试通知...")
        self.test_thread = QThread(self)
        self.test_worker = BarkTestWorker(
            service_url=config.bark_service_url,
            device_key=key,
            jump_url=None,
        )
        self.test_worker.moveToThread(self.test_thread)
        self.test_thread.started.connect(self.test_worker.run)
        self.test_worker.completed.connect(self._on_bark_test_completed)
        self.test_worker.finished.connect(self.test_thread.quit)
        self.test_worker.finished.connect(self.test_worker.deleteLater)
        self.test_thread.finished.connect(self._on_bark_test_finished)
        self.test_thread.finished.connect(self.test_thread.deleteLater)
        self.test_thread.start()

    @Slot(bool, str)
    def _on_bark_test_completed(self, success: bool, message: str) -> None:
        self.bark_result_label.setText(message)
        self.bark_result_label.setStyleSheet(
            "color: #176b3a;" if success else "color: #8b1e1e;"
        )

    @Slot()
    def _on_bark_test_finished(self) -> None:
        self.test_thread = None
        self.test_worker = None
        self.test_bark_button.setEnabled(True)

    def refresh_status(self) -> None:
        try:
            config = MonitorConfig.load(self.config_path)
        except MonitorConfigError:
            config = MonitorConfig()
        self.monitor_status.setText("已开启" if config.enabled else "已关闭")
        try:
            database = MonitorStateDatabase(self.database_path)
            run = database.latest_run()
            count = database.notification_count()
        except Exception:
            run = None
            count = 0
        if run:
            self.last_check_status.setText(str(run.get("finished_at") or "-"))
            self.read_status.setText(
                "成功" if run.get("read_success") else "失败"
            )
            self.data_source_status.setText(
                str(run.get("data_source") or "unknown")
            )
            self.matched_status.setText(str(run.get("matched_count") or 0))
            self.error_status.setText(
                str(run.get("error_message") or "-")
            )
            finished = self._parse_time(run.get("finished_at"))
            if finished is None:
                self.next_check_status.setText("-")
            else:
                next_time = finished + timedelta(
                    minutes=config.check_interval_minutes
                )
                self.next_check_status.setText(
                    next_time.isoformat(timespec="seconds")
                )
        else:
            self.last_check_status.setText("尚未运行")
            self.read_status.setText("-")
            self.next_check_status.setText("等待计划任务")
            self.data_source_status.setText("-")
            self.matched_status.setText("0")
            self.error_status.setText("-")
        self.notification_status.setText(str(count))
        self._update_mode_label()

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _update_mode_label(self) -> None:
        meta = (self.snapshot or {}).get("meta") or {}
        source = meta.get("data_source") if self.snapshot else None
        if source in {"network_live", "mini_program_live"}:
            text = (
                f"当前已有实时数据（{source}）。后台需要 Windows 微信、"
                "小程序登录态和交互式计划任务保持有效。"
            )
        else:
            text = (
                "测试模式：当前没有已确认的实时小程序数据。"
                "缓存和模拟数据只用于界面与测试，不会发送正式空位通知。"
            )
        self.mode_label.setText(text)
