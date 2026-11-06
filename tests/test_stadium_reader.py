from __future__ import annotations

import unittest
from typing import Any

from src.api.stadium_reader import (
    AuthenticationRequiredError,
    MalformedResponseError,
    StadiumReader,
    parse_intervals,
    parse_stadium_details,
    parse_venue_config,
)


DETAILS_RESPONSE = {
    "status": 1,
    "info": "success",
    "data": {
        "name": "翔安校区健身房",
        "details": "面向师生开放",
        "location": "翔安校区",
        "phone": "0592-0000000",
        "facilities": "容纳上限 95 人",
        "services": "管理员服务",
        "cover": "cover.jpg",
        "category_id": 8,
        "user_range": "student",
        "albums": [],
        "next_url": "/stadium/choose.html",
        "venue": [
            {
                "category_id": 8,
                "name": "健身房",
                "list": [
                    {
                        "week": "今天",
                        "date": "11月02日",
                        "is_subscribe": 0,
                        "venue_id": 123,
                    }
                ],
            }
        ],
    },
}


INTERVAL_RESPONSE = {
    "status": 1,
    "info": "success",
    "data": {
        "date_list": [
            {
                "week": "今天",
                "date": "11月02日",
                "date_int": "2026-11-02",
            }
        ],
        "column_list": [{"column_id": 9, "name": "健身房"}],
        "time_slot_list": [
            {
                "date": "2026-11-02",
                "week": "星期一",
                "week_name": "今天",
                "time_range": "18:00-19:00",
                "slots": [
                    {
                        "column_id": 9,
                        "area_name": "健身房",
                        "interval_id": 77,
                        "price": "0.00",
                        "status": "available",
                        "selected": 88,
                        "lock_reason": "",
                    }
                ],
            }
        ],
        "personal_num": 95,
        "team_num": 95,
        "add_auth": True,
        "venue_appointment_min_num": 0,
        "confirm_time": "半小时",
        "neighbor": 0,
        "is_can_choose": 1,
        "is_can_choose_tips": "",
    },
}


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.headers: dict[str, str] = {}
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs["data"]))
        return FakeResponse(self.responses.pop(0))


class StadiumReaderTests(unittest.TestCase):
    def test_parse_details(self) -> None:
        parsed = parse_stadium_details(DETAILS_RESPONSE)
        self.assertEqual(parsed["name"], "翔安校区健身房")
        self.assertEqual(parsed["location"], "翔安校区")
        self.assertEqual(parsed["venues"][0]["category_id"], 8)
        self.assertEqual(parsed["venue_ids"], [123])

    def test_parse_intervals_and_remaining_capacity(self) -> None:
        parsed = parse_intervals(INTERVAL_RESPONSE)
        self.assertEqual(len(parsed["slots"]), 1)
        slot = parsed["slots"][0]
        self.assertEqual(slot["remaining"], 7)
        self.assertEqual(slot["remaining_team"], 7)
        self.assertEqual(slot["status_text"], "可预约")
        self.assertTrue(slot["is_open"])

    def test_authentication_failure_is_not_reported_as_success(self) -> None:
        payload = {
            "status": 0,
            "info": "登录信息失效，请返回并重新进入",
            "data": [],
        }
        with self.assertRaises(AuthenticationRequiredError):
            parse_stadium_details(payload)

    def test_missing_status_is_rejected(self) -> None:
        with self.assertRaises(MalformedResponseError):
            parse_intervals({"data": {}})

    def test_string_zero_is_not_treated_as_true(self) -> None:
        parsed = parse_venue_config(
            {
                "status": 1,
                "info": "success",
                "data": {
                    "info": {
                        "needRemark": 0,
                        "isCanAppoint": "0",
                        "isCanAppointMsg": "closed",
                        "phone": "",
                        "verify_phone": "0",
                    }
                },
            }
        )
        self.assertFalse(parsed["is_can_appoint"])
        self.assertFalse(parsed["verify_phone"])

    def test_read_gym_snapshot_chains_both_read_endpoints(self) -> None:
        session = FakeSession([DETAILS_RESPONSE, INTERVAL_RESPONSE])
        reader = StadiumReader(
            session=session,
            min_request_interval=0,
        )

        snapshot = reader.read_gym_snapshot()

        self.assertTrue(snapshot["request_ok"])
        self.assertEqual(snapshot["venue_id"], 123)
        self.assertEqual(snapshot["user_range"], "student")
        self.assertEqual(len(snapshot["intervals"]["slots"]), 1)
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(
            session.calls[0][0].endswith(
                "/index/Stadium/getStadiumDetails"
            )
        )
        self.assertEqual(session.calls[0][1], {"id": 16})
        self.assertTrue(
            session.calls[1][0].endswith(
                "/stadium/interval/getInterval"
            )
        )
        self.assertEqual(
            session.calls[1][1],
            {
                "venue_id": 123,
                "stadium_id": 16,
                "user_range": "student",
                "category_id": 8,
            },
        )


if __name__ == "__main__":
    unittest.main()
