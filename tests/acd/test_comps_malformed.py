"""CompsRecord.parse must skip unparseable (encrypted/protected) records.

Source-protected ACD content stores comps records whose body is ciphertext:
the 124-byte record-name field is high-entropy noise with no UTF-16 NUL
terminator, so the Kaitai name parse runs off the end of its substream.
JAKL_LAUR_PROD.ACD carries 29 such records (its five protected AOIs);
before the skip logic they aborted the entire conversion with
EndOfStreamError. parse() must return None for them and still parse
well-formed records.
"""

import struct
from types import SimpleNamespace

from acd.record.comps import CompsRecord

FDFD_IDENTIFIER = 65021
HEADER_LEN = 155
NAME_OFFSET = 24
NAME_FIELD_LEN = 124


def _fdfd_record(name_bytes: bytes, tail_len: int = 40) -> SimpleNamespace:
    """Build a minimal stand-in for DatRecord: a 155-byte FDFD header
    followed by a record body, with the fields parse() touches populated."""
    header = bytearray(HEADER_LEN)
    struct.pack_into("<H", header, 4, 7)  # seq_number
    struct.pack_into("<H", header, 10, 1)  # record_type
    struct.pack_into("<I", header, 16, 1234)  # object_id
    struct.pack_into("<I", header, 20, 5678)  # parent_id
    header[NAME_OFFSET : NAME_OFFSET + NAME_FIELD_LEN] = name_bytes[
        :NAME_FIELD_LEN
    ].ljust(NAME_FIELD_LEN, b"\x00")
    buffer = bytes(header) + b"\x00" * tail_len
    return SimpleNamespace(
        identifier=FDFD_IDENTIFIER,
        len_record=len(buffer) + 8,
        record=SimpleNamespace(record_buffer=buffer),
    )


def test_well_formed_record_parses():
    name = "MyTag".encode("utf-16le") + b"\x00\x00"
    entry = CompsRecord.parse(_fdfd_record(name))
    assert entry is not None
    object_id, parent_id, record_name, seq_number, record_type, _ = entry
    assert object_id == 1234
    assert parent_id == 5678
    assert record_name == "MyTag"
    assert seq_number == 7
    assert record_type == 1


def test_unterminated_name_record_is_skipped():
    # Name field filled end-to-end with non-NUL bytes (encrypted noise):
    # no terminator inside the 124-byte substream.
    noise = b"\x41\x42" * (NAME_FIELD_LEN // 2)
    assert CompsRecord.parse(_fdfd_record(noise)) is None


def test_unknown_identifier_returns_none():
    rec = _fdfd_record(b"X\x00\x00\x00")
    rec.identifier = 12345
    assert CompsRecord.parse(rec) is None
