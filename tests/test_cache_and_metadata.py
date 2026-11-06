from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.api.cache import SnapshotCache
from src.api.stadium_reader import (
    AuthenticationRequiredError,
    StadiumReader,
)
from tests.test_stadium_reader import DETAILS_RESPONSE, INTERVAL_RESPONSE


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.headers: dict[str, str] = {}
        self.payloads = payloads
        self.calls = 0

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls += 1
        return FakeResponse(self.payloads.pop(0))


class CacheAndMetadataTests(unittest.TestCase):
    def test_success_has_live_metadata_and_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "latest.json"
            cache = SnapshotCache(cache_path)
            session = FakeSession([DETAILS_RESPONSE, INTERVAL_RESPONSE])
            reader = StadiumReader(
                session=session,
                cache=cache,
                min_request_interval=0,
            )

            snapshot = reader.read_gym_snapshot()
            meta = snapshot["meta"]
            self.assertEqual(meta["data_source"], "network_live")
            self.assertEqual(meta["http_status"], 200)
            self.assertEqual(meta["business_status"], 1)
            self.assertTrue(meta["request_success"])
            self.assertTrue(meta["parse_success"])
            self.assertIsNone(meta["error_type"])
            self.assertEqual(session.calls, 2)
            self.assertTrue(cache_path.exists())

            entry = cache.load()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.snapshot["meta"]["data_source"], "cache")
            self.assertIsNotNone(entry.snapshot["meta"]["cache_age"])

    def test_authentication_exception_contains_http_and_business_status(
        self,
    ) -> None:
        session = FakeSession(
            [
                {
                    "status": 0,
                    "info": "登录信息失效，请返回并重新进入",
                    "data": [],
                }
            ]
        )
        reader = StadiumReader(
            session=session,
            min_request_interval=0,
        )

        with self.assertRaises(AuthenticationRequiredError) as context:
            reader.read_gym_snapshot()

        meta = context.exception.diagnostics
        self.assertIsNotNone(meta)
        self.assertEqual(meta["data_source"], "unknown")
        self.assertEqual(meta["http_status"], 200)
        self.assertEqual(meta["business_status"], 0)
        self.assertTrue(meta["request_success"])
        self.assertFalse(meta["parse_success"])
        self.assertEqual(meta["error_type"], "authentication_required")


if __name__ == "__main__":
    unittest.main()
