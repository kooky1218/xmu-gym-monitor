from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@unittest.skipUnless(
    importlib.util.find_spec("PySide6"),
    "PySide6 is not installed",
)
class MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_snapshot_renders_table_rows(self) -> None:
        from src.api.stadium_reader import NoAuthentication
        from src.ui.main_window import MainWindow

        class FakeReader:
            auth_adapter = NoAuthentication()

        window = MainWindow(FakeReader())
        snapshot = {
            "campus": "翔安校区",
            "fetched_at": "2026-11-02T11:30:00+08:00",
            "venue": {"name": "翔安校区健身房"},
            "meta": {
                "data_source": "network_live",
                "fetched_at": "2026-11-02T11:30:00+08:00",
                "cache_age": 0,
                "http_status": 200,
                "business_status": 1,
                "request_success": True,
                "parse_success": True,
                "error_type": None,
            },
            "intervals": {
                "slots": [
                    {
                        "date": "2026-11-02",
                        "week_name": "今天",
                        "time_range": "18:00-19:00",
                        "area_name": "健身房",
                        "personal_capacity": 95,
                        "selected": 88,
                        "remaining": 7,
                        "status_text": "可预约",
                        "is_open": True,
                        "lock_reason": "",
                    }
                ]
            },
        }

        window._handle_success(snapshot)

        self.assertEqual(window.campus_value.text(), "翔安校区")
        self.assertEqual(window.venue_value.text(), "翔安校区健身房")
        self.assertEqual(
            window.result_value.text(),
            "读取成功（小程序实时页面）",
        )
        self.assertIn("network_live", window.source_value.text())
        self.assertIn("自动刷新", window.auto_refresh_label.text())
        self.assertEqual(window.table.rowCount(), 1)
        self.assertEqual(window.table.item(0, 6).text(), "7")
        window.close()
        window.deleteLater()
        self.app.processEvents()

    def test_empty_success_shows_explicit_empty_state(self) -> None:
        from src.api.stadium_reader import NoAuthentication
        from src.ui.main_window import MainWindow

        class FakeReader:
            auth_adapter = NoAuthentication()

        window = MainWindow(FakeReader())
        window._handle_success(
            {
                "campus": "翔安校区",
                "fetched_at": "2026-11-02T11:30:00+08:00",
                "venue": {"name": "翔安校区健身房"},
                "meta": {
                    "data_source": "network_live",
                    "fetched_at": "2026-11-02T11:30:00+08:00",
                    "cache_age": 0,
                    "http_status": 200,
                    "business_status": 1,
                    "request_success": True,
                    "parse_success": True,
                    "error_type": None,
                },
                "intervals": {"slots": []},
            }
        )

        self.assertEqual(window.table.rowCount(), 1)
        self.assertIn("没有可展示", window.table.item(0, 0).text())
        window.close()
        window.deleteLater()
        self.app.processEvents()

    def test_auto_refresh_runs_while_hidden_in_tray(self) -> None:
        from src.api.stadium_reader import NoAuthentication
        from src.ui.main_window import MainWindow

        class FakeReader:
            auth_adapter = NoAuthentication()

        window = MainWindow(FakeReader())
        window.tray_icon = SimpleNamespace(isVisible=lambda: True)
        window.hide()
        with patch.object(window, "_start_refresh") as start_refresh:
            window._auto_refresh()
        start_refresh.assert_called_once_with(notify_after_read=False)
        window._allow_quit = True
        window.close()
        window.deleteLater()
        self.app.processEvents()

    def test_failed_refresh_displays_cache_explicitly(self) -> None:
        from src.api.cache import CacheEntry
        from src.api.stadium_reader import NoAuthentication
        from src.ui.main_window import MainWindow

        cached_snapshot = {
            "campus": "翔安校区",
            "venue": {"name": "翔安校区健身房"},
            "meta": {
                "data_source": "cache",
                "fetched_at": "2026-11-02T10:00:00+08:00",
                "cache_age": 3600,
                "http_status": 200,
                "business_status": 1,
                "request_success": True,
                "parse_success": True,
                "error_type": None,
            },
            "intervals": {
                "slots": [
                    {
                        "date": "2026-11-02",
                        "week_name": "今天",
                        "time_range": "18:00-19:00",
                        "area_name": "健身房",
                        "personal_capacity": 95,
                        "selected": 90,
                        "remaining": 5,
                        "status_text": "可预约",
                        "is_open": True,
                        "lock_reason": "",
                    }
                ]
            },
        }

        class FakeReader:
            auth_adapter = NoAuthentication()

            def load_cached_snapshot(self):
                return CacheEntry(
                    snapshot=cached_snapshot,
                    saved_at="2026-11-02T10:00:00+08:00",
                    age_seconds=3600,
                    path=Path("latest.json"),
                )

        window = MainWindow(FakeReader())
        failure = {
            "message": "登录信息失效",
            "meta": {
                "data_source": "unknown",
                "fetched_at": "2026-11-02T11:00:00+08:00",
                "cache_age": None,
                "http_status": 200,
                "business_status": 0,
                "request_success": True,
                "parse_success": False,
                "error_type": "authentication_required",
            },
        }

        with patch("src.ui.main_window.QMessageBox.warning"):
            window._handle_failure(failure)

        self.assertIn("历史缓存", window.result_value.text())
        self.assertIn("cache", window.source_value.text())
        self.assertEqual(window.table.rowCount(), 1)
        self.assertEqual(window.table.item(0, 6).text(), "5")
        window.close()
        window.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
