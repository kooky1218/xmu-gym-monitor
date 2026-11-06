from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


def configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def main() -> int:
    configure_logging()
    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication
    except ImportError:
        logging.getLogger(__name__).error(
            "PySide6 未安装，请执行 python -m pip install -r requirements.txt"
        )
        return 2

    from src.api.cache import SnapshotCache
    from src.monitor.miniprogram_reader import MiniProgramStadiumReader
    from src.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("厦大体育健身房数据")
    app.setFont(QFont("Microsoft YaHei UI", 10))

    reader = MiniProgramStadiumReader(
        cache=SnapshotCache(PROJECT_ROOT / "cache" / "latest_snapshot.json"),
    )
    window = MainWindow(reader)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
