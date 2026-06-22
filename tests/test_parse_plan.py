import unittest

from esg_selective_mineru.page_scan import score_page
from esg_selective_mineru.parse_plan import build_parse_plan


class SelectivePlanTests(unittest.TestCase):
    def test_score_page_detects_table_like_esg_page(self):
        scan = score_page(1, "环境绩效 指标 单位 2024 用水量 吨 100 温室气体排放总量 吨 200")
        self.assertGreaterEqual(scan.mineru_score, 35)
        self.assertIn("table_terms", scan.reasons)

    def test_build_parse_plan_selects_high_score_pages(self):
        scans = [
            {"page_number": 1, "mineru_score": 10, "number_count": 0, "scan_quality": "text_layer_ok"},
            {"page_number": 2, "mineru_score": 60, "number_count": 20, "scan_quality": "text_layer_ok"},
        ]
        plan = build_parse_plan(scans, mineru_score_threshold=35, max_mineru_pages=5)
        self.assertEqual(plan["mineru_pages"], [2])


if __name__ == "__main__":
    unittest.main()
