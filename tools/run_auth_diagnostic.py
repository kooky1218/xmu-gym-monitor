from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.api.stadium_reader import StadiumReader, StadiumReaderError
from src.platform.windows_state import snapshot_windows_state


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "logs" / "auth_diagnostic.jsonl"


def _unknown_meta() -> dict[str, Any]:
    return {
        "data_source": "unknown",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cache_age": None,
        "http_status": None,
        "business_status": None,
        "request_success": False,
        "parse_success": False,
        "error_type": "unexpected_error",
    }


def _append_json_line(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one read-only XMU gym authentication diagnostic."
    )
    parser.add_argument(
        "--scenario",
        required=True,
        choices=("A", "B", "C", "D"),
    )
    parser.add_argument(
        "--target-date",
        default="2026-11-03",
        help="Informational target date; getInterval itself has no date parameter.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
    )
    parser.add_argument(
        "--use-system-proxy",
        action="store_true",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")

    args = _build_parser().parse_args(argv)
    before = snapshot_windows_state()
    started = time.monotonic()
    run_at = datetime.now().astimezone()
    snapshot: dict[str, Any] | None = None
    error: StadiumReaderError | None = None

    reader = StadiumReader(
        trust_env=args.use_system_proxy,
        min_request_interval=0.5,
        cache=None,
    )
    try:
        snapshot = reader.read_gym_snapshot()
    except StadiumReaderError as exc:
        error = exc
    elapsed_ms = int((time.monotonic() - started) * 1000)
    after = snapshot_windows_state()

    if snapshot is not None:
        meta = snapshot.get("meta") or _unknown_meta()
        message = None
        outcome = "parsed"
    else:
        meta = (error.diagnostics if error else None) or _unknown_meta()
        message = str(error) if error else "unknown error"
        outcome = "failed"

    record = {
        "scenario": args.scenario,
        "run_at": run_at.isoformat(timespec="seconds"),
        "elapsed_ms": elapsed_ms,
        "stadium_id": 16,
        "category_id": 8,
        "target_date": args.target_date,
        "target_date_note": "getInterval does not accept date as a request field",
        "data_source": meta.get("data_source"),
        "fetched_at": meta.get("fetched_at"),
        "cache_age": meta.get("cache_age"),
        "http_status": meta.get("http_status"),
        "business_status": meta.get("business_status"),
        "request_success": bool(meta.get("request_success")),
        "parse_success": bool(meta.get("parse_success")),
        "error_type": meta.get("error_type"),
        "outcome": outcome,
        "message": message,
        "windows_state_before": before,
        "windows_state_after": after,
    }
    output_path = Path(args.output)
    _append_json_line(output_path, record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"result_file={output_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
