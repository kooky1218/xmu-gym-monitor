from __future__ import annotations

import unittest

import requests

from src.notification.bark_notifier import BarkNotifier
from src.notification.credential_store import BarkCredentialStore


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        *,
        headers: dict[str, str] | None = None,
        payload: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload or {"code": 200, "message": "success"}

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, results: list[object]) -> None:
        self.results = results
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(
        self,
        service_name: str,
        username: str,
        password: str,
    ) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


class BarkNotifierTests(unittest.TestCase):
    def make_notifier(
        self,
        session: FakeSession,
        sleeps=None,
        *,
        retry_max_seconds: float = 0,
    ) -> BarkNotifier:
        return BarkNotifier(
            service_url="https://api.day.app",
            device_key="test-device-key",
            session=session,
            max_retries=2,
            retry_base_seconds=0,
            retry_max_seconds=retry_max_seconds,
            sleep=(sleeps.append if sleeps is not None else lambda _: None),
        )

    def test_success_uses_official_push_endpoint_and_payload(self) -> None:
        session = FakeSession([FakeResponse()])
        result = self.make_notifier(session).send(
            title="title",
            body="body",
            url="https://example.com",
            dedup_seconds=0,
        )
        self.assertTrue(result.success)
        self.assertEqual(session.calls[0]["url"], "https://api.day.app/push")
        payload = session.calls[0]["json"]
        self.assertEqual(payload["device_key"], "test-device-key")
        self.assertEqual(payload["title"], "title")
        self.assertEqual(payload["body"], "body")
        self.assertEqual(payload["url"], "https://example.com")

    def test_server_error_retries_then_succeeds(self) -> None:
        sleeps: list[float] = []
        session = FakeSession([FakeResponse(500), FakeResponse(200)])
        result = self.make_notifier(
            session,
            sleeps,
            retry_max_seconds=10,
        ).send(
            title="title",
            body="body",
            dedup_seconds=0,
        )
        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(sleeps), 1)

    def test_server_error_reports_server_error_after_retry_limit(self) -> None:
        session = FakeSession(
            [FakeResponse(500), FakeResponse(500), FakeResponse(500)]
        )
        result = self.make_notifier(session).send(
            title="title",
            body="body",
            dedup_seconds=0,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "server_error")
        self.assertEqual(result.attempts, 3)

    def test_rate_limit_honors_retry_after(self) -> None:
        sleeps: list[float] = []
        session = FakeSession(
            [
                FakeResponse(429, headers={"Retry-After": "3"}),
                FakeResponse(200),
            ]
        )
        result = self.make_notifier(
            session,
            sleeps,
            retry_max_seconds=10,
        ).send(
            title="title",
            body="body",
            dedup_seconds=0,
        )
        self.assertTrue(result.success)
        self.assertEqual(sleeps, [3.0])

    def test_client_error_is_not_retried(self) -> None:
        session = FakeSession([FakeResponse(400)])
        result = self.make_notifier(session).send(
            title="title",
            body="body",
            dedup_seconds=0,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "client_error")
        self.assertEqual(len(session.calls), 1)

    def test_network_error_returns_failure_after_retries(self) -> None:
        session = FakeSession(
            [
                requests.ConnectionError("offline"),
                requests.ConnectionError("offline"),
                requests.ConnectionError("offline"),
            ]
        )
        result = self.make_notifier(session).send(
            title="title",
            body="body",
            dedup_seconds=0,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "network_error")
        self.assertEqual(result.attempts, 3)

    def test_identical_message_is_short_time_deduplicated(self) -> None:
        session = FakeSession([FakeResponse()])
        notifier = self.make_notifier(session)
        first = notifier.send(title="same", body="same", dedup_seconds=60)
        second = notifier.send(title="same", body="same", dedup_seconds=60)
        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(second.provider_message_id, "deduplicated")
        self.assertEqual(len(session.calls), 1)

    def test_test_notification_always_sends(self) -> None:
        session = FakeSession([FakeResponse(), FakeResponse()])
        notifier = self.make_notifier(session)
        notifier.send_test()
        notifier.send_test()
        self.assertEqual(len(session.calls), 2)


class CredentialStoreTests(unittest.TestCase):
    def test_round_trip_and_delete(self) -> None:
        store = BarkCredentialStore(FakeKeyring())
        store.set_key("secret-key")
        self.assertTrue(store.has_key())
        self.assertEqual(store.get_key(), "secret-key")
        store.delete_key()
        self.assertFalse(store.has_key())


if __name__ == "__main__":
    unittest.main()
