from __future__ import annotations

import unittest
from datetime import date

from src.monitor.miniprogram_reader import (
    MiniProgramAuthenticationRequiredError,
    MiniProgramStadiumReader,
    detail_rows_to_slots,
    parse_choose_slots,
    parse_date_tabs,
    parse_detail_dates,
)
from src.monitor.miniprogram_ui_reader import MiniProgramUiSnapshot


def snapshot(*texts: str, hour: str = "2026-11-05T20:00:00+08:00"):
    return MiniProgramUiSnapshot(
        fetched_at=hour,
        window_name="厦大体育",
        process_id=6196,
        texts=tuple(texts),
        source="test_bridge",
    )


class FakeUiReader:
    def __init__(self, *pages: MiniProgramUiSnapshot) -> None:
        self.pages = list(pages)
        self.clicks: list[str] = []

    def capture(self) -> MiniProgramUiSnapshot:
        return self.pages[0]

    def click(
        self,
        target: str,
        *,
        occurrence: int = 0,
    ) -> MiniProgramUiSnapshot:
        self.clicks.append(target)
        if len(self.pages) > 1:
            self.pages.pop(0)
        return self.pages[0]


class MappingUiReader:
    def __init__(
        self,
        initial: MiniProgramUiSnapshot,
        pages_by_click: dict[str, MiniProgramUiSnapshot],
    ) -> None:
        self.initial = initial
        self.pages_by_click = pages_by_click
        self.clicks: list[str] = []

    def capture(self) -> MiniProgramUiSnapshot:
        return self.initial

    def click(
        self,
        target: str,
        *,
        occurrence: int = 0,
    ) -> MiniProgramUiSnapshot:
        self.clicks.append(target)
        return self.pages_by_click[target]


class MiniProgramReaderTests(unittest.TestCase):
    def test_detail_dates_distinguish_entry_open_and_absent(self) -> None:
        rows = parse_detail_dates(
            [
                "场馆详情",
                "翔安校区健身房",
                "今天",
                "11月05日",
                "暂无",
                "周五",
                "11月06日",
                "预定",
            ],
            today=date(2026, 11, 5),
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date"], "2026-11-05")
        self.assertFalse(rows[0]["is_open"])
        self.assertEqual(rows[1]["date"], "2026-11-06")
        self.assertTrue(rows[1]["is_open"])

    def test_date_entry_slot_does_not_invent_remaining_count(self) -> None:
        rows = parse_detail_dates(
            ["今天", "11月05日", "预定"],
            today=date(2026, 11, 5),
        )
        slot = detail_rows_to_slots(rows)[0]
        self.assertTrue(slot["is_open"])
        self.assertIsNone(slot["remaining"])
        self.assertEqual(slot["availability_kind"], "date_entry")
        self.assertEqual(slot["time_range"], "日期可预约")

    def test_reader_returns_live_snapshot_from_detail_page(self) -> None:
        ui = FakeUiReader(
            snapshot(
                "场馆详情",
                "翔安校区健身房",
                "今天",
                "11月05日",
                "暂无",
                "周五",
                "11月06日",
                "暂无",
            )
        )
        reader = MiniProgramStadiumReader(
            ui_reader=ui,
            navigation_wait_seconds=0,
        )
        payload = reader.read_gym_snapshot(
            target_dates=["2026-11-05", "2026-11-06"]
        )
        self.assertEqual(payload["meta"]["data_source"], "mini_program_live")
        self.assertEqual(payload["meta"]["page_kind"], "detail")
        self.assertEqual(len(payload["intervals"]["slots"]), 2)
        self.assertFalse(payload["intervals"]["slots"][1]["is_open"])
        self.assertEqual(ui.clicks, [])

    def test_reader_expands_bookable_date_into_time_slots(self) -> None:
        detail = snapshot(
            "场馆详情",
            "翔安校区健身房",
            "今天",
            "11月05日",
            "暂无",
            "周五",
            "11月06日",
            "预定",
        )
        choose_1106 = snapshot(
            "选择场次",
            "今天",
            "11月05日",
            "周五",
            "11月06日",
            "18:00-19:00",
            "90/95",
            "19:00-20:00",
            "95/95",
        )
        choose_1105 = snapshot(
            "选择场次",
            "今天",
            "11月05日",
            "周五",
            "11月06日",
            "18:00-19:00",
            "70/95",
            "19:00-20:00",
            "88/95",
        )
        ui = MappingUiReader(
            detail,
            {
                "预定": choose_1106,
                "11月05日": choose_1105,
                "11月06日": choose_1106,
            },
        )
        reader = MiniProgramStadiumReader(
            ui_reader=ui,
            navigation_wait_seconds=0,
        )
        payload = reader.read_gym_snapshot(target_dates=[])
        self.assertEqual(payload["meta"]["page_kind"], "choose")
        self.assertEqual(ui.clicks, ["预定", "11月05日", "11月06日"])
        slots = payload["intervals"]["slots"]
        self.assertEqual(len(slots), 4)
        self.assertEqual(slots[0]["date"], "2026-11-05")
        self.assertEqual(slots[0]["time_range"], "18:00-19:00")
        self.assertEqual(slots[0]["remaining"], 25)
        self.assertTrue(slots[0]["is_open"])

    def test_reader_navigates_home_then_venue_list(self) -> None:
        ui = FakeUiReader(
            snapshot("厦大体育", "场馆预约"),
            snapshot(
                "场馆预约",
                "所有场馆",
                "翔安校区健身房",
            ),
            snapshot(
                "场馆详情",
                "翔安校区健身房",
                "今天",
                "11月05日",
                "暂无",
            ),
        )
        reader = MiniProgramStadiumReader(
            ui_reader=ui,
            navigation_wait_seconds=0,
        )
        payload = reader.read_gym_snapshot(
            target_dates=["2026-11-05"]
        )
        self.assertEqual(ui.clicks, ["场馆预约", "翔安校区健身房"])
        self.assertEqual(payload["venue"]["name"], "翔安校区健身房")

    def test_reader_detects_expired_login(self) -> None:
        ui = FakeUiReader(
            snapshot(
                "厦大体育",
                "登录信息失效，请返回并重新进入",
            )
        )
        reader = MiniProgramStadiumReader(
            ui_reader=ui,
            navigation_wait_seconds=0,
        )
        with self.assertRaises(MiniProgramAuthenticationRequiredError):
            reader.read_gym_snapshot(target_dates=["2026-11-05"])

    def test_choose_page_parses_visible_capacity_fractions(self) -> None:
        texts = [
            "选择场次",
            "今天",
            "11月05日",
            "周五",
            "11月06日",
            "08:00-09:00",
            "3/95",
            "95/95",
            "09:00-10:00",
            "0/95",
        ]
        self.assertEqual(
            [row["date"] for row in parse_date_tabs(
                texts,
                today=date(2026, 11, 5),
            )],
            ["2026-11-05", "2026-11-06"],
        )
        slots = parse_choose_slots(
            texts,
            selected_date="2026-11-05",
        )
        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0]["remaining"], 92)
        self.assertTrue(slots[0]["is_open"])
        self.assertEqual(slots[1]["remaining"], 0)
        self.assertFalse(slots[1]["is_open"])


if __name__ == "__main__":
    unittest.main()
