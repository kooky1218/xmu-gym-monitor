from __future__ import annotations

import sys


def main() -> int:
    if any(
        arg in {
            "--run-once",
            "--daemon",
            "--simulate-notification",
            "--send-test-notification",
            "--help",
        }
        for arg in sys.argv[1:]
    ):
        from src.service.background_worker import main as worker_main

        return worker_main(sys.argv[1:])

    from src.main import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
