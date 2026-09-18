import unittest
from unittest.mock import patch

from backend.app.routers import data, me
from backend.app.services import report_generator
from backend.app.services.csv_store import add_ai_usage_metrics


class AIUsageMetricsTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"date": "2026-09-01", "username": "alice", "organization": "org", "cost_center_name": "Center", "model": "model-a", "quantity": "1", "gross_amount": "1", "net_amount": "0", "input": "100", "output": "20", "cache_read": "300", "cache_write": "40"},
            {"date": "2026-09-02", "username": "ALICE", "organization": "org", "cost_center_name": "Center", "model": "model-a", "quantity": "2", "gross_amount": "2", "net_amount": "0", "input": "50", "output": "10", "cache_read": "25", "cache_write": "0"},
            {"date": "2026-09-01", "username": "bob", "organization": "other", "cost_center_name": "Other", "model": "model-b", "quantity": "3", "gross_amount": "3", "net_amount": "0", "input": "9999"},
        ]

    def test_accumulates_all_four_fields(self):
        total = {}
        add_ai_usage_metrics(total, {"input": "100", "output": "20", "cache_read": "300", "cache_write": "40"})
        add_ai_usage_metrics(total, {"input": "50", "output": "0", "cache_read": "25", "cache_write": "2.5"})
        self.assertEqual(total, {"input": 150, "output": 20, "cache_read": 325, "cache_write": 42.5})

    def test_missing_and_invalid_values_are_not_reported_as_zero(self):
        total = {}
        add_ai_usage_metrics(total, {})
        add_ai_usage_metrics(total, {"input": "", "output": "NaN", "cache_read": "inf", "cache_write": "invalid"})
        self.assertEqual(total, {"input": None, "output": None, "cache_read": None, "cache_write": None})
        add_ai_usage_metrics(total, {"input": "0", "output": None, "cache_write": "-1"})
        self.assertEqual(total["input"], 0)
        self.assertIsNone(total["output"])
        self.assertIsNone(total["cache_write"])

    def test_admin_filters_apply_before_metric_aggregation(self):
        with patch.object(data, "load_all_csv_records", return_value=self.records):
            result = data._build_ai_usage_section(["org"], ["Center"], "2026-09-01", "2026-09-01", {"alice"})
        self.assertEqual(result["kpi"]["input"], 100)
        for key in ("users", "daily_trend", "model_breakdown", "org_breakdown", "cost_center_breakdown"):
            self.assertEqual(result[key][0]["cache_read"], 300)

    def test_regular_user_only_receives_own_metrics_in_date_range(self):
        with patch.object(me, "load_all_csv_records", return_value=self.records):
            result = me._my_ai_usage("Alice", "2026-09-02", "2026-09-02")
        self.assertEqual(result["kpi"]["input"], 50)
        self.assertEqual(result["model_breakdown"][0]["output"], 10)
        self.assertEqual(result["daily_trend"][0]["cache_write"], 0)

    def test_owner_aggregation_preserves_metrics(self):
        result = report_generator._build_ai_usage_section(self.records[:2])
        self.assertEqual(result["kpi"]["input"], 150)
        self.assertEqual(result["model_breakdown"][0]["cache_read"], 325)
        self.assertEqual(result["users"][0]["cache_write"], 0)

    def test_legacy_records_return_unknown_metrics_in_all_views(self):
        record = {key: value for key, value in self.records[0].items() if key not in ("input", "output", "cache_read", "cache_write")}
        with (
            patch.object(data, "load_all_csv_records", return_value=[record]),
            patch.object(me, "load_all_csv_records", return_value=[record]),
        ):
            results = [
                data._build_ai_usage_section([], [], "", ""),
                me._my_ai_usage("alice", "", ""),
                report_generator._build_ai_usage_section([record]),
            ]
        for result in results:
            self.assertIsNone(result["kpi"]["input"])
            self.assertIsNone(result["model_breakdown"][0]["cache_read"])


if __name__ == "__main__":
    unittest.main()