from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from src.monitor.config import MonitorConfig
from src.notification.credential_store import BarkCredentialStore


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(
        self,
        service_name: str,
        username: str,
        password: str,
    ) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


@unittest.skipUnless(
    importlib.util.find_spec("PySide6"),
    "PySide6 is not installed",
)
class MonitorSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_dynamic_options_and_save(self) -> None:
        from PySide6.QtCore import QDate
        from src.ui.monitor_settings import MonitorSettingsDialog

        snapshot = {
            "meta": {"data_source": "network_live"},
            "intervals": {
                "slots": [
                    {
                        "date": "2026-11-06",
                        "time_range": "18:00-19:00",
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "monitor.json"
            database_path = Path(temp_dir) / "state.sqlite3"
            MonitorConfig().save(config_path)
            keyring = BarkCredentialStore(FakeKeyring())
            dialog = MonitorSettingsDialog(
                snapshot=snapshot,
                config_path=config_path,
                database_path=database_path,
                credential_store=keyring,
            )
            dialog.date_edit.setDate(QDate(2026, 11, 6))
            dialog.add_date()
            slot_item = next(
                dialog.slot_list.item(index)
                for index in range(dialog.slot_list.count())
                if dialog.slot_list.item(index).text() == "18:00-19:00"
            )
            slot_item.setSelected(True)
            dialog.enabled_checkbox.setChecked(True)
            dialog.bark_key_edit.setText("test-key")

            dialog.save_config()

            saved = MonitorConfig.load(config_path)
            self.assertEqual(saved.target_dates, ["2026-11-06"])
            self.assertEqual(saved.target_slots, ["18:00-19:00"])
            self.assertTrue(saved.enabled)
            self.assertEqual(keyring.get_key(), "test-key")
            self.assertIn("network_live", dialog.mode_label.text())
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
