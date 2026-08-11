import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tag_analyzer.comment_pipeline import PLCCommentPipeline


class TestACDFixtureDiscovery(unittest.TestCase):
    def test_finds_newest_acd_file_recursively(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            older = repo_root / "tests" / "acd" / "older.ACD"
            newer = repo_root / "nested" / "newer.acd"
            older.parent.mkdir(parents=True)
            newer.parent.mkdir(parents=True)
            older.touch()
            newer.touch()
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))

            self.assertEqual(
                TestDirectACDDeliverables._find_newest_acd_file(repo_root),
                newer,
            )


class TestDirectACDDeliverables(unittest.TestCase):
    @staticmethod
    def _find_newest_acd_file(repo_root):
        acd_files = [
            path
            for path in repo_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".acd"
        ]
        if not acd_files:
            return None
        return max(
            acd_files,
            key=lambda path: (path.stat().st_mtime_ns, str(path).casefold()),
        )

    def setUp(self):
        self.pipeline = PLCCommentPipeline()
        repo_root = Path(__file__).resolve().parents[1]
        self.acd_fixture = self._find_newest_acd_file(repo_root)
        if self.acd_fixture is None:
            self.skipTest("No .ACD fixture found in the repository")
        self.test_deliverables_dir = self.acd_fixture.parent / f"{self.acd_fixture.stem}_deliverables"

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
