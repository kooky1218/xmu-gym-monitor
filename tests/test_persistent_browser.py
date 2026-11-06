from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.auth.login import read_auth_state, write_auth_state
from src.auth.persistent_browser import (
    BrowserRequestSession,
    chrome_executable,
)


class FakePage:
    def __init__(self, payload: dict) -> None:
        self.response = {
            "status": 200,
            "headers": {"content-type": "application/json"},
            "json": payload,
        }
        self.expressions: list[str] = []

    def evaluate(self, expression: str, **kwargs) -> dict:
        self.expressions.append(expression)
        return self.response


class BrowserSessionTests(unittest.TestCase):
    def test_logged_in_when_details_returns_success(self) -> None:
        page = FakePage(
            {"status": 1, "data": {"name": "翔安校区健身房"}}
        )
        session = BrowserRequestSession(page)
        self.assertTrue(session.is_logged_in())
        self.assertIn("getStadiumDetails", page.expressions[0])

    def test_login_expiry_is_detected(self) -> None:
        page = FakePage(
            {"status": 0, "info": "登录信息失效", "data": []}
        )
        self.assertFalse(BrowserRequestSession(page).is_logged_in())

    def test_chrome_or_edge_is_available(self) -> None:
        self.assertTrue(Path(chrome_executable()).exists())

    def test_auth_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "auth_state.json"
            with patch("src.auth.login.STATE_PATH", path):
                write_auth_state(
                    "logged_in",
                    message="ok",
                    checked_at=datetime(2026, 11, 5, 18, 0),
                )
                value = read_auth_state()
            self.assertEqual(value["status"], "logged_in")
            self.assertEqual(value["message"], "ok")


if __name__ == "__main__":
    unittest.main()
