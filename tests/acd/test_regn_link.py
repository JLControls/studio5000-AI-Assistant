import struct
import unittest

from acd.l5x import export_l5x
from acd.zip.write_dat import _restore_tag_refs


def link_record(key, ordinal, routine_id, current_rung_id, next_rung_id, tail):
    return struct.pack(
        "<HHIII6s",
        key,
        ordinal,
        routine_id,
        current_rung_id,
        next_rung_id,
        tail,
    )


class RegnLinkParserTest(unittest.TestCase):
    def test_restore_tag_refs_encodes_new_project_tag_without_rewriting_opcodes(self):
        """A changed rung may reference a tag absent from the original rung."""
        restored = _restore_tag_refs(
            "XIC(Existing_Tag)XIO(New_Interlock)OTE(New_Interlock);",
            "XIC(@10@);",
            {0x10: "Existing_Tag", 0x20: "New_Interlock", 0x30: "X"},
        )

        self.assertEqual(
            "XIC(@10@)XIO(@20@)OTE(@20@);",
            restored,
        )
        self.assertNotIn("New_Interlock", restored)

    def test_recovers_v38_comment_key_and_rung_chain(self):
        """Dropping or misaligning RegnLink records must lose this mapping."""
        routine_id = 0x2E3EA47B
        rung_0 = 0x4BD161E0
        rung_1 = 0x628E95E3
        data = (
            b"noise-prefix"
            + link_record(0x4FEC, 39, routine_id, rung_0, rung_1, b"\x00\x00\x02\x00\x00\x01")
            + link_record(0x833F, 10, routine_id, rung_1, 0xFFFFFFFF, b"\xff" * 6)
            + b"noise-suffix"
        )

        parse = getattr(export_l5x, "_parse_regn_links", lambda *_args: [])
        actual = parse(data, {routine_id}, {rung_0, rung_1})

        self.assertEqual(
            [
                (0x4FEC, routine_id, rung_0, rung_1),
                (0x833F, routine_id, rung_1, 0xFFFFFFFF),
            ],
            actual,
        )

    def test_rejects_records_that_do_not_reference_known_objects(self):
        routine_id = 0x2E3EA47B
        rung_0 = 0x4BD161E0
        data = link_record(0x4FEC, 39, routine_id, rung_0, 0xFFFFFFFF, b"\x00" * 6)

        parse = getattr(export_l5x, "_parse_regn_links", lambda *_args: [])

        self.assertEqual([], parse(data, set(), {rung_0}))
        self.assertEqual([], parse(data, {routine_id}, set()))


if __name__ == "__main__":
    unittest.main()
