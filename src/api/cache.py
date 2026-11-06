from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class CacheError(Exception):
    """Raised when a snapshot cache cannot be read or written safely."""


@dataclass(frozen=True)
class CacheEntry:
    snapshot: dict[str, Any]
    saved_at: str
    age_seconds: int
    path: Path


class SnapshotCache:
    """Atomic JSON cache for successful, non-credentialed snapshots."""

    FORMAT_VERSION = 1

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def save(self, snapshot: dict[str, Any]) -> None:
        saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        document = {
            "format_version": self.FORMAT_VERSION,
            "saved_at": saved_at,
            "snapshot": copy.deepcopy(snapshot),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(document, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as exc:
            raise CacheError("无法写入本地数据快照") from exc
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def load(self) -> CacheEntry | None:
        if not self.path.exists():
            return None
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CacheError("无法读取本地数据快照") from exc

        if not isinstance(document, dict):
            raise CacheError("本地数据快照格式无效")
        snapshot = document.get("snapshot")
        saved_at = document.get("saved_at")
        if not isinstance(snapshot, dict) or not isinstance(saved_at, str):
            raise CacheError("本地数据快照缺少必要字段")

        age_seconds = self._age_seconds(saved_at)
        loaded = copy.deepcopy(snapshot)
        meta = loaded.setdefault("meta", {})
        if not isinstance(meta, dict):
            raise CacheError("本地快照 meta 字段格式无效")
        meta["data_source"] = "cache"
        meta["cache_age"] = age_seconds
        return CacheEntry(
            snapshot=loaded,
            saved_at=saved_at,
            age_seconds=age_seconds,
            path=self.path,
        )

    @staticmethod
    def _age_seconds(saved_at: str) -> int:
        try:
            parsed = datetime.fromisoformat(saved_at)
        except ValueError:
            return 0
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return max(
            int((datetime.now().astimezone() - parsed).total_seconds()),
            0,
        )
