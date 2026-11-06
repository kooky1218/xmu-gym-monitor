from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.monitor.miniprogram_ui_reader import (
    MiniProgramBridgeError,
    MiniProgramUiSnapshot,
    MiniProgramUiReader,
    MiniProgramWindowNotFound,
)


def snapshot(*texts: str) -> MiniProgramUiSnapshot:
    return MiniProgramUiSnapshot(
        fetched_at="2026-11-06T14:00:00+08:00",
        window_name="厦大体育",
        process_id=6196,
        texts=tuple(texts),
        source="test",
    )


class FakeControl:
    def __init__(
        self,
        name: str,
        *,
        process_id: int = 100,
    ) -> None:
        self.Name = name
        self.ProcessId = process_id


class FakeRoot:
    def __init__(self, children: list[FakeControl]) -> None:
        self.children = children

    def GetChildren(self):
        return self.children


class MiniProgramUiReaderTests(unittest.TestCase):
    def test_capture_reads_window_text(self) -> None:
        window = FakeControl("厦大体育", process_id=321)
        controls = [
            (FakeControl("翔安校区健身房"), 0),
            (FakeControl("18:00-19:00"), 1),
            (FakeControl("剩余 3"), 1),
            (FakeControl("18:00-19:00"), 1),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "ui.txt"
            fake_auto = SimpleNamespace(
                GetRootControl=lambda: FakeRoot([window]),
                WalkControl=lambda *_args, **_kwargs: iter(controls),
            )
            with (
                patch(
                    "src.monitor.miniprogram_ui_reader._import_uiautomation",
                    return_value=fake_auto,
                ),
                patch(
                    "src.monitor.miniprogram_ui_reader.DEBUG_DUMP_PATH",
                    output,
                ),
            ):
                snapshot = MiniProgramUiReader(
                    prefer_bridge=False
                ).capture()
            self.assertEqual(snapshot.window_name, "厦大体育")
            self.assertEqual(snapshot.process_id, 321)
            self.assertEqual(snapshot.texts.count("18:00-19:00"), 2)
            self.assertEqual(output.read_text(encoding="utf-8"), snapshot.page_text)

    def test_missing_window_raises(self) -> None:
        fake_auto = SimpleNamespace(
            GetRootControl=lambda: FakeRoot([]),
        )
        with patch(
            "src.monitor.miniprogram_ui_reader._import_uiautomation",
            return_value=fake_auto,
        ):
            with self.assertRaises(MiniProgramWindowNotFound):
                MiniProgramUiReader(prefer_bridge=False).capture()

    def test_bridge_output_is_parsed_as_page_text(self) -> None:
        class FakeBridge:
            available = True

            def run(self, action: str = "read", target: str = "") -> str:
                return (
                    "PID 6196\n"
                    "OK\n"
                    "ControlType.Window: 厦大体育\n"
                    "  ControlType.Text: 场馆详情\n"
                    "  ControlType.Text: 翔安校区健身房\n"
                    "  ControlType.Text: 11月05日\n"
                    "  ControlType.Text: 暂无\n"
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "ui.txt"
            with patch(
                "src.monitor.miniprogram_ui_reader.DEBUG_DUMP_PATH",
                output,
            ):
                snapshot = MiniProgramUiReader(
                    bridge=FakeBridge()
                ).capture()
        self.assertEqual(snapshot.process_id, 6196)
        self.assertEqual(snapshot.page_kind, "detail")
        self.assertIn("翔安校区健身房", snapshot.texts)

    def test_bridge_window_error_has_clear_type(self) -> None:
        class FakeBridge:
            available = True

            def run(self, action: str = "read", target: str = "") -> str:
                return "ERROR WINDOW_NOT_FOUND\n"

        with self.assertRaises(MiniProgramWindowNotFound):
            MiniProgramUiReader(bridge=FakeBridge()).capture()

    def test_bridge_other_error_is_not_hidden(self) -> None:
        class FakeBridge:
            available = True

            def run(self, action: str = "read", target: str = "") -> str:
                return "ERROR Timeout\n"

        with self.assertRaises(MiniProgramBridgeError):
            MiniProgramUiReader(bridge=FakeBridge()).capture()

    def test_last_visible_page_title_wins_over_stale_title(self) -> None:
        detail = snapshot(
            "厦大体育",
            "选择场次",
            "场馆详情",
            "翔安校区健身房",
            "11月06日",
            "暂无",
        )
        choose = snapshot(
            "厦大体育",
            "场馆详情",
            "选择场次",
            "11月06日",
            "18:00-19:00",
            "90/95",
        )
        self.assertEqual(detail.page_kind, "detail")
        self.assertEqual(choose.page_kind, "choose")


if __name__ == "__main__":
    unittest.main()
