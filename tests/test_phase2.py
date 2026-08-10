from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from phase2.queue import DEFAULT_LABEL_TYPE, DEFAULT_TOPIC, SHANGHAI, parse_schedule, parse_skus, validate_record


class Phase2ParsingTests(unittest.TestCase):
    def test_parses_feishu_millisecond_timestamp(self) -> None:
        value = int(datetime(2026, 7, 25, 20, 30, tzinfo=SHANGHAI).timestamp() * 1000)
        parsed = parse_schedule(value)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.strftime("%Y-%m-%d %H:%M"), "2026-07-25 20:30")

    def test_sku_parser_deduplicates_and_limits_are_checked_elsewhere(self) -> None:
        self.assertEqual(parse_skus("80000001\n80000001，80000002"), (
            "80000001",
            "80000002",
        ))


class Phase2EligibilityTests(unittest.TestCase):
    def test_approved_future_record_is_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "test.mp4"
            video.touch()
            schedule = datetime(2026, 7, 25, 20, 30, tzinfo=SHANGHAI)
            record = {
                "record_id": "rec1",
                "fields": {
                    "任务编号": "JD-TEST",
                    "视频文件": str(video),
                    "发布标题": "墨狩船钓竿弯弓实测",
                    "商品SKU": "80000001\n80000002",
                    "参与话题": DEFAULT_TOPIC,
                    "标签类型": DEFAULT_LABEL_TYPE,
                    "定时发布时间": int(schedule.timestamp() * 1000),
                    "审核状态": "已批准",
                    "发布状态": "待审核",
                },
            }
            job, reasons = validate_record(
                record,
                now=datetime(2026, 7, 25, 16, 0, tzinfo=SHANGHAI),
            )
            self.assertEqual(reasons, [])
            self.assertIsNotNone(job)
            self.assertEqual(job.scheduled_publish_time, "2026-07-25 20:30")
            self.assertEqual(len(job.skus), 2)

    def test_pending_review_and_short_lead_time_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "test.mp4"
            video.touch()
            schedule = datetime(2026, 7, 25, 17, 0, tzinfo=SHANGHAI)
            record = {
                "record_id": "rec2",
                "fields": {
                    "任务编号": "JD-TEST",
                    "视频文件": str(video),
                    "发布标题": "墨狩船钓竿弯弓实测",
                    "商品SKU": "80000001",
                    "参与话题": DEFAULT_TOPIC,
                    "标签类型": DEFAULT_LABEL_TYPE,
                    "定时发布时间": int(schedule.timestamp() * 1000),
                    "审核状态": "待人工审核",
                    "发布状态": "待审核",
                },
            }
            job, reasons = validate_record(
                record,
                now=datetime(2026, 7, 25, 16, 0, tzinfo=SHANGHAI),
            )
            self.assertIsNone(job)
            self.assertIn("审核状态尚未批准", reasons)
            self.assertIn("定时发布时间必须至少晚于当前时间2小时", reasons)


if __name__ == "__main__":
    unittest.main()
