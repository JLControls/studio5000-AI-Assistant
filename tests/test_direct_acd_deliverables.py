import os
import shutil
import unittest
from pathlib import Path

from tag_analyzer.comment_pipeline import PLCCommentPipeline


class TestDirectACDDeliverables(unittest.TestCase):
    def setUp(self):
        self.pipeline = PLCCommentPipeline()
        self.acd_fixture = Path("tests/acd/ModernTHAWROOM021722.ACD").resolve()
        self.assertTrue(self.acd_fixture.exists(), "Fixture ModernTHAWROOM021722.ACD must exist")
        self.test_deliverables_dir = self.acd_fixture.parent / "ModernTHAWROOM021722_deliverables"

    def tearDown(self):
        if self.test_deliverables_dir.exists():
            shutil.rmtree(self.test_deliverables_dir, ignore_errors=True)

    def test_deliverables_folder_alongside_acd(self):
        decisions = [
            {
                "TYPE": "Comment",
                "SCOPE": "MainRoutine",
                "NAME": "N101[20].1",
                "PROPOSED_DESCRIPTION": "Test Valve Signal",
                "rung_number": 0,
            }
        ]

        res = self.pipeline.generate_deliverables(
            decisions=decisions,
            file_path=self.acd_fixture,
            edit_acd=False,
        )

        self.assertTrue(Path(res["csv_delta"]).exists())
        self.assertTrue(Path(res["html_report"]).exists())
        self.assertEqual(Path(res["csv_delta"]).parent.resolve(), self.test_deliverables_dir)

    def test_direct_acd_editing(self):
        decisions = [
            {
                "TYPE": "Comment",
                "SCOPE": "MainRoutine",
                "NAME": "N101[20].1",
                "PROPOSED_DESCRIPTION": "Test Valve Signal",
                "routine": "MainRoutine",
                "rung_number": 0,
                "PROPOSED_RUNG_TEXT": "XIC(N101[21].11)OTL(N101[20].1); NOP();",
            }
        ]

        res = self.pipeline.generate_deliverables(
            decisions=decisions,
            file_path=self.acd_fixture,
            edit_acd=True,
        )

        self.assertIn("updated_acd", res)
        updated_acd_path = Path(res["updated_acd"])
        self.assertTrue(updated_acd_path.exists())
        self.assertEqual(updated_acd_path.parent.resolve(), self.test_deliverables_dir)
        self.assertGreater(updated_acd_path.stat().st_size, 1000000)


if __name__ == "__main__":
    unittest.main()
