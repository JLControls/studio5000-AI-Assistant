import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from l5x_analyzer.acd_offline_convert import convert_acd_to_l5x
from l5x_analyzer.l5x_semantic_validation import compare_l5x


def rung_comments(path: Path):
    root = ET.parse(path).getroot()
    comments = {}
    for program in root.findall(".//Program"):
        program_name = program.get("Name", "")
        for routine in program.findall("./Routines/Routine"):
            routine_name = routine.get("Name", "")
            for rung in routine.findall("./RLLContent/Rung"):
                comment = rung.find("./Comment")
                text = (comment.text or "").strip() if comment is not None else ""
                if text:
                    comments[(program_name, routine_name, rung.get("Number", ""))] = text
    return comments


def normalize_comment(text: str) -> str:
    """Compare Studio and ACD comment text independent of line wrapping."""
    return re.sub(r"\s+", " ", text).strip()


def tag_operand_comments(path: Path):
    root = ET.parse(path).getroot()
    comments = {}
    for tag in root.findall(".//Controller/Tags/Tag"):
        for comment in tag.findall("./Comments/Comment"):
            text = (comment.text or "").strip()
            if text:
                comments[(tag.get("Name", ""), comment.get("Operand", ""))] = normalize_comment(text)
    return comments


def top_level_descriptions(path: Path):
    root = ET.parse(path).getroot()
    result = {}
    for kind, query in (
        ("Tag", ".//Controller/Tags/Tag"),
        ("Module", ".//Controller/Modules/Module"),
    ):
        for element in root.findall(query):
            description = element.find("./Description")
            if description is not None and normalize_comment(description.text or ""):
                result[(kind, element.get("Name", ""))] = normalize_comment(description.text or "")
    return result


def _default_fixtures():
    acd = os.environ.get("THAWROOM_ACD")
    native = os.environ.get("THAWROOM_NATIVE_L5X")
    if not acd or not Path(acd).exists():
        cand = Path(__file__).parent / "acd" / "ModernTHAWROOM021722" / "ModernTHAWROOM021722.ACD"
        if cand.exists():
            acd = str(cand)
    if not native or not Path(native).exists():
        cand = Path(__file__).parent / "acd" / "ModernTHAWROOM021722" / "ModernTHAWROOM021722.L5X"
        if cand.exists():
            native = str(cand)
    return acd, native


class AcdL5xFidelityTest(unittest.TestCase):
    def test_semantic_report_identifies_losses_and_changes(self):
        reference = """<RSLogix5000Content><Controller><Tags><Tag Name="A" TagType="Base" DataType="DINT"><Description>kept</Description></Tag></Tags><Programs><Program Name="P"><Routines><Routine Name="R" Type="RLL"><RLLContent><Rung Number="0" Type="N"><Text>XIC(A);</Text></Rung></RLLContent></Routine></Routines></Program></Programs></Controller></RSLogix5000Content>"""
        generated = """<RSLogix5000Content><Controller><Tags><Tag Name="A" TagType="Base" DataType="BOOL"/></Tags><Programs><Program Name="P"><Routines><Routine Name="R" Type="RLL"><RLLContent><Rung Number="0" Type="N"><Text>XIC(B);</Text></Rung></RLLContent></Routine></Routines></Program></Programs></Controller></RSLogix5000Content>"""
        with tempfile.TemporaryDirectory(prefix="l5x_parity_test_") as temp_dir:
            reference_path = Path(temp_dir) / "reference.L5X"
            generated_path = Path(temp_dir) / "generated.L5X"
            reference_path.write_text(reference, encoding="utf-8")
            generated_path.write_text(generated, encoding="utf-8")
            report = compare_l5x(generated_path, reference_path)
        self.assertEqual("differences", report["status"])
        self.assertFalse(report["import_safe"])
        self.assertEqual(["Controller/Tags/Tag:A"], report["categories"]["descriptions"]["losses"])
        self.assertEqual(["A"], report["categories"]["controller_tags"]["changed"])
        self.assertEqual(["P/R/0"], report["categories"]["rungs"]["changed"])

    def test_preserves_native_rung_comments(self):
        """Removing Comments.Dat ingestion or comment serialization must fail this test."""
        acd_path, native_path = _default_fixtures()
        if not acd_path or not native_path:
            self.skipTest("Set THAWROOM_ACD and THAWROOM_NATIVE_L5X for integration regression")

        with tempfile.TemporaryDirectory(prefix="acd_l5x_test_") as temp_dir:
            generated_path = Path(temp_dir) / "generated.L5X"
            result = convert_acd_to_l5x(acd_path, generated_path, pretty=False)
            self.assertTrue(result["success"], result)
            native_comments = rung_comments(Path(native_path))
            generated_comments = rung_comments(generated_path)
            self.assertEqual(native_comments.keys(), generated_comments.keys())
            self.assertEqual(
                {key: normalize_comment(value) for key, value in native_comments.items()},
                {key: normalize_comment(value) for key, value in generated_comments.items()},
            )

    def test_preserves_native_tag_operand_comments(self):
        """Removing operand-comment serialization must fail this test."""
        acd_path, native_path = _default_fixtures()
        if not acd_path or not native_path:
            self.skipTest("Set THAWROOM_ACD and THAWROOM_NATIVE_L5X for integration regression")

        with tempfile.TemporaryDirectory(prefix="acd_l5x_test_") as temp_dir:
            generated_path = Path(temp_dir) / "generated.L5X"
            result = convert_acd_to_l5x(acd_path, generated_path, pretty=False)
            self.assertTrue(result["success"], result)
            self.assertEqual(
                tag_operand_comments(Path(native_path)),
                tag_operand_comments(generated_path),
            )

    def test_preserves_controller_tag_and_module_descriptions(self):
        acd_path, native_path = _default_fixtures()
        if not acd_path or not native_path:
            self.skipTest("Set THAWROOM_ACD and THAWROOM_NATIVE_L5X for integration regression")

        with tempfile.TemporaryDirectory(prefix="acd_l5x_test_") as temp_dir:
            generated_path = Path(temp_dir) / "generated.L5X"
            result = convert_acd_to_l5x(acd_path, generated_path, pretty=False)
            self.assertTrue(result["success"], result)
            self.assertEqual(
                top_level_descriptions(Path(native_path)),
                top_level_descriptions(generated_path),
            )


if __name__ == "__main__":
    unittest.main()
