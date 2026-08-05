import struct
import unittest

from acd.record import comments


class V38Utf16CommentTest(unittest.TestCase):
    def test_preserves_full_multi_digit_operand_reference(self):
        """Consuming the first UTF-16 code unit as a length must fail this test."""
        body = (
            b"\x00" * 8
            + struct.pack("<I", 0x12345678)
            + b"\x00\x01\x00\x00"
            + "[18]".encode("utf-16le")
            + b"\x00\x00"
            + b"\x00" * 12
            + b"Calibrated Temperature\x00"
        )

        parse = getattr(comments, "_parse_utf16_comment_body", lambda _body: None)

        self.assertEqual(
            (0x12345678, "[18]", "Calibrated Temperature"),
            parse(body),
        )


if __name__ == "__main__":
    unittest.main()
