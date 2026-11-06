from __future__ import annotations

from datetime import datetime
from pathlib import Path

import uiautomation as auto


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "work" / "miniprogram_ui_dump.txt"


def main() -> int:
    lines: list[str] = [
        f"checked_at={datetime.now().astimezone().isoformat()}",
    ]
    desktop = auto.GetRootControl()
    matches: list[auto.Control] = []
    all_windows: list[str] = []
    for window in desktop.GetChildren():
        try:
            window_name = window.Name or ""
            all_windows.append(
                f"name={window_name!r} class={window.ClassName!r} "
                f"pid={window.ProcessId}"
            )
            if "厦大体育" in window_name:
                matches.append(window)
        except Exception:
            continue

    lines.append(f"matches={len(matches)}")
    lines.append(f"top_level_count={len(all_windows)}")
    lines.extend(f"TOP {item}" for item in all_windows[:100])
    for window in matches:
        lines.append(
            f"WINDOW name={window.Name!r} class={window.ClassName!r} "
            f"pid={window.ProcessId}"
        )
        for control, depth in auto.WalkControl(window, maxDepth=30):
            try:
                name = (control.Name or "").replace("\n", "\\n")
                if not name:
                    continue
                lines.append(
                    f"{'  ' * depth}{control.ControlTypeName}: {name}"
                )
            except Exception:
                continue

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
