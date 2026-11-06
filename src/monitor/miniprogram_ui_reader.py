from __future__ import annotations

import contextlib
import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEBUG_DUMP_PATH = PROJECT_ROOT / "work" / "miniprogram_uia_snapshot.txt"
BRIDGE_PATH = PROJECT_ROOT / "tools" / "MiniProgramUiBridge.exe"
BRIDGE_LOCK_PATH = PROJECT_ROOT / "data" / "miniprogram_bridge.lock"


class MiniProgramUiError(Exception):
    """Raised when the mini-program accessibility tree cannot be read."""


class MiniProgramWindowNotFound(MiniProgramUiError):
    """Raised when the XMU sports mini-program window is not open."""


class MiniProgramBridgeError(MiniProgramUiError):
    """Raised when the out-of-process UI Automation bridge fails."""


@dataclass(frozen=True)
class MiniProgramUiSnapshot:
    fetched_at: str
    window_name: str
    process_id: int | None
    texts: tuple[str, ...]
    source: str = "desktop_uia"

    @property
    def page_text(self) -> str:
        return "\n".join(self.texts)

    @property
    def page_kind(self) -> str:
        text = self.page_text
        last_choose = text.rfind("选择场次")
        last_detail = text.rfind("场馆详情")
        if last_choose >= 0 and last_detail >= 0:
            return (
                "detail"
                if last_detail > last_choose
                else "choose"
            )
        if "选择场次" in text:
            return "choose"
        if "场馆详情" in text:
            return "detail"
        if "所有场馆" in text or "翔安校区健身房" in text:
            return "venue_list"
        if "场馆预约" in text:
            return "home"
        return "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "window_name": self.window_name,
            "process_id": self.process_id,
            "source": self.source,
            "page_kind": self.page_kind,
            "texts": list(self.texts),
        }


class MiniProgramBridgeClient:
    """File-based protocol for the validated interactive-desktop UIA bridge."""

    def __init__(
        self,
        executable: Path | str = BRIDGE_PATH,
        *,
        timeout: float = 15.0,
    ) -> None:
        self.executable = Path(executable)
        self.timeout = timeout
        self.work_dir = PROJECT_ROOT / "work"
        self.command_path = self.work_dir / "uia_command.txt"
        self.output_path = self.work_dir / "uia_bridge_output.txt"
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.executable.is_file()

    def run(
        self,
        action: str = "read",
        target: str = "",
        index: int = 0,
    ) -> str:
        if not self.available:
            raise MiniProgramBridgeError("未找到小程序 UI Automation 桥程序")

        with self._lock:
            with _cross_process_lock(BRIDGE_LOCK_PATH):
                self.work_dir.mkdir(parents=True, exist_ok=True)
                self.output_path.unlink(missing_ok=True)
                self.command_path.write_text(
                    f"{action.strip()}\n{target.strip()}\n{max(index, 0)}\n",
                    encoding="utf-8",
                )
                creation_flags = (
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0
                )
                try:
                    completed = subprocess.run(
                        [str(self.executable)],
                        cwd=str(PROJECT_ROOT),
                        capture_output=True,
                        timeout=self.timeout,
                        creationflags=creation_flags,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    self.command_path.unlink(missing_ok=True)
                    raise MiniProgramBridgeError(
                        f"小程序读取桥执行失败：{exc.__class__.__name__}"
                    ) from exc

                if not self.output_path.exists():
                    detail = completed.stderr.decode(
                        "utf-8",
                        errors="replace",
                    ).strip()
                    raise MiniProgramBridgeError(
                        "小程序读取桥没有返回页面内容"
                        + (f"：{detail}" if detail else "")
                    )
                return self.output_path.read_text(encoding="utf-8")


def _parse_bridge_tree(output: str) -> tuple[list[str], int | None]:
    texts: list[str] = []
    process_id: int | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line == "OK":
            continue
        if line.startswith("ERROR "):
            if "WINDOW_NOT_FOUND" in line:
                raise MiniProgramWindowNotFound(
                    "未找到“厦大体育”小程序窗口，请先打开并保持登录"
                )
            raise MiniProgramBridgeError(line.removeprefix("ERROR ").strip())
        if line.startswith("PID "):
            try:
                process_id = int(line.removeprefix("PID ").strip())
            except ValueError:
                process_id = None
            continue
        if not line.startswith("ControlType."):
            continue
        _, separator, raw_name = line.partition(": ")
        if not separator:
            continue
        name = (
            raw_name.replace("\\r", "\r")
            .replace("\\n", "\n")
            .strip()
        )
        if name:
            texts.append(name)
    if not texts:
        raise MiniProgramBridgeError("小程序页面没有可读取的控件文本")
    return texts, process_id


class MiniProgramUiReader:
    """Read-only adapter for text exposed by the logged-in mini-program."""

    def __init__(
        self,
        window_title: str = "厦大体育",
        *,
        bridge: MiniProgramBridgeClient | None = None,
        prefer_bridge: bool = True,
    ) -> None:
        self.window_title = window_title
        self.bridge = bridge or MiniProgramBridgeClient()
        self.prefer_bridge = prefer_bridge

    def capture(self) -> MiniProgramUiSnapshot:
        if self.prefer_bridge and self.bridge.available:
            output = self.bridge.run("read")
            texts, process_id = _parse_bridge_tree(output)
            return self._save_snapshot(
                process_id=process_id,
                texts=texts,
                source="desktop_uia_bridge",
            )
        return self._capture_with_python_uia()

    def click(
        self,
        target: str,
        *,
        occurrence: int = 0,
    ) -> MiniProgramUiSnapshot:
        if not target.strip():
            raise ValueError("点击目标不能为空")
        if occurrence < 0:
            raise ValueError("控件序号不能小于 0")
        if self.prefer_bridge and self.bridge.available:
            output = self.bridge.run("click", target, occurrence)
            texts, process_id = _parse_bridge_tree(output)
            return self._save_snapshot(
                process_id=process_id,
                texts=texts,
                source="desktop_uia_bridge",
            )
        if occurrence:
            raise MiniProgramBridgeError(
                "Python UIA 回退模式暂不支持重复控件序号"
            )
        return self._click_with_python_uia(target)

    def back(self) -> MiniProgramUiSnapshot:
        if self.prefer_bridge and self.bridge.available:
            output = self.bridge.run("back")
            texts, process_id = _parse_bridge_tree(output)
            return self._save_snapshot(
                process_id=process_id,
                texts=texts,
                source="desktop_uia_bridge",
            )
        raise MiniProgramBridgeError("Python UIA 回退模式暂不支持页面返回")

    @staticmethod
    def list_top_level_windows(limit: int = 100) -> list[dict[str, Any]]:
        auto = _import_uiautomation()
        rows: list[dict[str, Any]] = []
        for window in auto.GetRootControl().GetChildren():
            try:
                rows.append(
                    {
                        "name": str(window.Name or ""),
                        "class_name": str(window.ClassName or ""),
                        "process_id": int(window.ProcessId),
                    }
                )
            except Exception:
                continue
            if len(rows) >= limit:
                break
        return rows

    def _find_window(self):
        auto = _import_uiautomation()
        desktop = auto.GetRootControl()
        for window in desktop.GetChildren():
            try:
                if (window.Name or "").strip() == self.window_title:
                    return window
            except Exception:
                continue
        raise MiniProgramWindowNotFound(
            "未找到“厦大体育”小程序窗口，请先打开并保持登录"
        )

    def _capture_with_python_uia(self) -> MiniProgramUiSnapshot:
        auto = _import_uiautomation()
        window = self._find_window()
        texts: list[str] = []
        for control, _depth in auto.WalkControl(window, maxDepth=40):
            try:
                name = (control.Name or "").strip()
                if name:
                    texts.append(name)
            except Exception:
                continue
        return self._save_snapshot(
            process_id=int(window.ProcessId),
            texts=texts,
            source="python_uia",
        )

    def _click_with_python_uia(
        self,
        target: str,
    ) -> MiniProgramUiSnapshot:
        auto = _import_uiautomation()
        window = self._find_window()
        control = window.TextControl(searchDepth=40, Name=target)
        if not control.Exists(2, 0.3):
            raise MiniProgramBridgeError(f"未找到控件“{target}”")
        control.Click(simulateMove=False)
        return self._capture_with_python_uia()

    def _save_snapshot(
        self,
        *,
        process_id: int | None,
        texts: list[str],
        source: str,
    ) -> MiniProgramUiSnapshot:
        snapshot = MiniProgramUiSnapshot(
            fetched_at=datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            window_name=self.window_title,
            process_id=process_id,
            texts=tuple(texts),
            source=source,
        )
        DEBUG_DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEBUG_DUMP_PATH.write_text(snapshot.page_text, encoding="utf-8")
        return snapshot


def _import_uiautomation():
    try:
        import uiautomation as auto
    except ImportError as exc:
        raise MiniProgramUiError(
            "未安装 uiautomation，无法直接读取小程序窗口"
        ) from exc
    return auto


@contextlib.contextmanager
def _cross_process_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            acquired = True
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
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
