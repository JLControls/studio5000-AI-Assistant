# Offline ACD Data-Table Value & Preset Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Backlog. The current exporter still contains primitive-zero fallback behavior; the binary offsets and public decoder contract are not yet proven by tracked golden fixtures.

**Goal:** Extract actual controller snapshot values, timer presets (`.PRE`), accumulator values (`.ACC`), counter presets, PID tuning setpoints, and analog scaling parameters directly from offline `.ACD` databases during `convert_acd_to_l5x` / `load_acd`, while making missing-value provenance explicit.

**Architecture:** Create a binary data table decoder module `src/acd/record/dat_table.py` (`TagValueDecoder`). In Studio 5000 `.ACD` archives, each tag record references a `_data_table_instance` pointing to a binary data record in `Comps.Dat` (record type 256 / `extended_records[0x66]`). The decoder unpacks scalar primitives (`BOOL`, `SINT`, `INT`, `DINT`, `LINT`, `REAL`, `LREAL`, `STRING`), built-in structures (`TIMER`, `COUNTER`, `CONTROL`), and nested UDTs/arrays. Wire this decoder into `src/acd/l5x/elements.py` so `<Data Format="Decorated">` and `<Data Format="L5K">` serialize live snapshot data.

**Tech Stack:** Python 3.12, binary struct decoding, IEEE-754 single/double precision floats, SQLite / `comps` table, XML serialization, pytest.

---

## Global Constraints

- Value decoding must be completely offline without requiring a live controller connection or Studio 5000 SDK.
- Support all standard Logix atomic data types:
  - `BOOL`: 1-bit / 1-byte boolean (0 or 1)
  - `SINT`: 1-byte signed integer (`int8`, -128 to 127)
  - `INT`: 2-byte little-endian signed integer (`int16`, -32,768 to 32,767)
  - `DINT`: 4-byte little-endian signed integer (`int32`, -2,147,483,648 to 2,147,483,647)
  - `LINT`: 8-byte little-endian signed integer (`int64`)
  - `REAL`: 4-byte IEEE-754 single-precision float (`float32`), formatted cleanly (e.g. `125.5` or `1.0e+04`)
  - `LREAL`: 8-byte IEEE-754 double-precision float (`float64`)
  - `STRING`: 4-byte DINT length header followed by ASCII/UTF-8 character buffer.
- Support built-in structures:
  - `TIMER` (12 bytes): `(Flags: u32, PRE: i32, ACC: i32)`. Extract `PRE`, `ACC`, `.EN = bool(Flags & 0x80000000)`, `.TT = bool(Flags & 0x40000000)`, `.DN = bool(Flags & 0x20000000)`.
  - `COUNTER` (12 bytes): `(Flags: u32, PRE: i32, ACC: i32)`. Extract `PRE`, `ACC`, `.CU = bool(Flags & 0x80000000)`, `.CD = bool(Flags & 0x40000000)`, `.DN = bool(Flags & 0x20000000)`, `.OV = bool(Flags & 0x10000000)`, `.UN = bool(Flags & 0x08000000)`.
  - `CONTROL` (12 bytes): `(LEN: i32, POS: i32, Flags: u32)`.
- Support UDT structures by calculating member byte offsets and recursively decoding member fields.
- Graceful degradation: If a tag's data record is missing, empty, or shorter than expected, emit a typed missing-value result with a warning and coverage/provenance entry. A zero may be used for compatibility serialization only when the result marks it as an unavailable snapshot value; it must not be presented as an observed controller value.
- Snapshot semantics: decoded values come from the saved ACD data table, not a live controller. Preserve source artifact identity and conversion warnings in exported metadata.
- All tests must pass with `PYTHONPATH=src python3 -m pytest tests/acd/`.

---

## File Map

Create:
- `src/acd/record/dat_table.py` — core `TagValueDecoder`, primitive unpackers, struct decoders, and UDT alignment helpers.
- `tests/acd/test_dat_table_values.py` — unit and regression tests for primitive decoding, struct decoding, UDT recursion, and end-to-end L5X export value validation.

Modify:
- `src/acd/l5x/elements.py` — update `Tag`, `_member_decorated_xml`, `_array_member_xml`, `_struct_members_xml`, and `_generate_decorated` to consume decoded tag values instead of hardcoded zero strings.
- `src/acd/l5x/export_l5x.py` — extract data table records during project building and pass `TagValueDecoder` to `TagBuilder` / `ProjectBuilder`.

Do not modify:
- `tests/test_direct_acd_deliverables.py` (pre-existing worktree modification).
- Unrelated Kaitai generated parsers under `src/acd/generated/`.

---

### Task 1: Build comprehensive failing unit tests for data table decoding

**Files:**
- Create: `tests/acd/test_dat_table_values.py`

**Canonical interface (resolve before implementation):**
```python
class TagValueDecoder:
    def __init__(self, data_records: Mapping[int, bytes], data_types: Mapping[str, Any]): ...
    def decode_tag_value(self, data_table_instance: int, data_type: str, dimensions: Optional[str] = None) -> Any: ...

    @classmethod
    def from_cursor(cls, cur: sqlite3.Cursor, data_types: Mapping[str, Any]): ...
```

The cursor adapter is an extraction boundary, not the public decoder contract.
Keep `decode_tag` as a compatibility alias only if existing callers require it; do not maintain two independently shaped APIs (`decode_tag` versus `decode_tag_value`).

- [ ] **Step 1: Write test cases covering all data types and structures.**
  Create `tests/acd/test_dat_table_values.py` with:
  1. `test_decode_primitive_scalars`: Decode mock binary buffers for `DINT` (e.g. `123456`), `INT` (`-500`), `SINT` (`42`), `REAL` (`125.75`), `BOOL` (`True`).
  2. `test_decode_timer_structure`: Decode 12-byte buffer `struct.pack("<III", 0x80000000, 600000, 1500)` -> `{"PRE": 600000, "ACC": 1500, "EN": 1, "TT": 0, "DN": 0}`.
  3. `test_decode_counter_structure`: Decode 12-byte buffer `struct.pack("<III", 0x20000000, 10, 10)` -> `{"PRE": 10, "ACC": 10, "CU": 0, "CD": 0, "DN": 1, "OV": 0, "UN": 0}`.
  4. `test_decode_string_type`: Decode `struct.pack("<I", 5) + b"Hello\x00\x00..."` -> `"Hello"`.
  5. `test_decode_udt_members`: Decode multi-member struct (e.g. SCP or custom UDT).
  6. `test_missing_record_reports_unavailable_value`: When `data_table_instance=0` or invalid, return a typed unavailable result and warning without aborting conversion.

  ```python
  import struct
  import pytest
  from acd.record.dat_table import TagValueDecoder

  def test_decode_timer_structure():
      decoder = TagValueDecoder(data_records={}, data_types={})
      # flags = EN (0x80000000) | DN (0x20000000) = 0xA0000000
      raw_payload = struct.pack("<III", 0xA0000000, 5000, 5000)
      val = decoder.unpack_timer(raw_payload)
      assert val["PRE"] == 5000
      assert val["ACC"] == 5000
      assert val["EN"] == 1
      assert val["DN"] == 1
      assert val["TT"] == 0
  ```

- [ ] **Step 2: Run pytest to inspect test failures.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/test_dat_table_values.py -q
  ```
  Expected result: Failures because `TagValueDecoder` does not yet exist.

---

### Task 2: Implement `TagValueDecoder` in `src/acd/record/dat_table.py`

**Files:**
- Create: `src/acd/record/dat_table.py`

- [ ] **Step 1: Implement primitive unpackers and struct helpers.**
  In `src/acd/record/dat_table.py`:
  - `unpack_primitive(raw_bytes: bytes, data_type: str) -> Any`
  - `unpack_timer(raw_bytes: bytes) -> Dict[str, Any]`
  - `unpack_counter(raw_bytes: bytes) -> Dict[str, Any]`
  - `unpack_control(raw_bytes: bytes) -> Dict[str, Any]`
  - `unpack_string(raw_bytes: bytes) -> str`

  ```python
  import struct
  from typing import Any, Dict, List, Optional, Union
  from sqlite3 import Cursor

  class TagValueDecoder:
      def __init__(self, cur: Optional[Cursor] = None):
          self._cur = cur

      def _extract_record_payload(self, data_table_instance: int) -> Optional[bytes]:
          if not self._cur or not data_table_instance:
              return None
          self._cur.execute(
              "SELECT record FROM comps WHERE object_id=?",
              (data_table_instance,)
          )
          row = self._cur.fetchone()
          if not row:
              return None
          raw_rec = bytes(row[0])
          # Look for attribute 0x66 (data payload) in record or extract payload tail
          # Type 256 record: payload length at offset -4 or attribute header
          if len(raw_rec) > 12:
              # Check for attribute 0x66 marker
              idx = raw_rec.rfind(b"\x66\x00\x00\x00")
              if idx != -1 and idx + 8 <= len(raw_rec):
                  payload_len = struct.unpack_from("<I", raw_rec, idx + 4)[0]
                  if idx + 8 + payload_len <= len(raw_rec):
                      return raw_rec[idx + 8 : idx + 8 + payload_len]
              # Fallback: last bytes
              return raw_rec[12:]
          return None

      def unpack_primitive(self, data: bytes, dt: str) -> Any:
          dt = dt.upper()
          if not data:
              return 0.0 if dt in ("REAL", "LREAL") else 0
          if dt == "REAL":
              return struct.unpack_from("<f", data, 0)[0] if len(data) >= 4 else 0.0
          elif dt == "LREAL":
              return struct.unpack_from("<d", data, 0)[0] if len(data) >= 8 else 0.0
          elif dt in ("DINT", "UDINT"):
              return struct.unpack_from("<i", data, 0)[0] if len(data) >= 4 else 0
          elif dt in ("INT", "UINT"):
              return struct.unpack_from("<h", data, 0)[0] if len(data) >= 2 else 0
          elif dt in ("SINT", "USINT"):
              return struct.unpack_from("<b", data, 0)[0] if len(data) >= 1 else 0
          elif dt == "BOOL":
              return 1 if (data[0] & 1) else 0
          elif dt == "LINT":
              return struct.unpack_from("<q", data, 0)[0] if len(data) >= 8 else 0
          return 0

      def unpack_timer(self, data: bytes) -> Dict[str, Any]:
          if not data or len(data) < 12:
              return {"PRE": 0, "ACC": 0, "EN": 0, "TT": 0, "DN": 0}
          flags, pre, acc = struct.unpack_from("<Iii", data, 0)
          return {
              "PRE": pre,
              "ACC": acc,
              "EN": 1 if (flags & 0x80000000) else 0,
              "TT": 1 if (flags & 0x40000000) else 0,
              "DN": 1 if (flags & 0x20000000) else 0,
          }

      def unpack_counter(self, data: bytes) -> Dict[str, Any]:
          if not data or len(data) < 12:
              return {"PRE": 0, "ACC": 0, "CU": 0, "CD": 0, "DN": 0, "OV": 0, "UN": 0}
          flags, pre, acc = struct.unpack_from("<Iii", data, 0)
          return {
              "PRE": pre,
              "ACC": acc,
              "CU": 1 if (flags & 0x80000000) else 0,
              "CD": 1 if (flags & 0x40000000) else 0,
              "DN": 1 if (flags & 0x20000000) else 0,
              "OV": 1 if (flags & 0x10000000) else 0,
              "UN": 1 if (flags & 0x08000000) else 0,
          }
  ```

- [ ] **Step 2: Implement UDT and array recursive decoding.**
  Add `decode_tag_value(data_table_instance, data_type, dimensions)` returning typed dictionaries and lists matching the verified structure layout. Do not guess offsets: each supported structure requires a golden byte fixture and an explicit unsupported-layout diagnostic.

- [ ] **Step 3: Run unit tests and verify `TagValueDecoder` passes.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/test_dat_table_values.py -q
  ```
  Expected result: All unit tests pass.

---

### Task 3: Integrate `TagValueDecoder` into `src/acd/l5x/elements.py` and `export_l5x.py`

**Files:**
- Modify: `src/acd/l5x/elements.py`
- Modify: `src/acd/l5x/export_l5x.py`

- [ ] **Step 1: Attach `_value` to `Tag` objects and pass `TagValueDecoder`.**
  In `TagBuilder.build()` (`src/acd/l5x/elements.py`), extract records once, construct the canonical decoder (through `from_cursor` if needed), decode the tag value from `r.main_record.data_table_instance`, and store both `Tag.value` and its availability/provenance.
- [ ] **Step 2: Update Decorated XML generators to format actual values.**
  In `_member_decorated_xml`, `_struct_members_xml`, and `_generate_decorated`:
  - When formatting primitive values, format `value` (`f"{value:.7g}"` for REAL, `str(value)` for integers/bools) instead of using static `_PRIMITIVE_DECORATED_ZERO`.
  - For `TIMER`, emit actual `PRE`, `ACC`, `EN`, `TT`, `DN` values from `tag.value`.
  - For `COUNTER`, emit actual `PRE`, `ACC`, `CU`, `CD`, `DN`, `OV`, `UN` values.
  - For array elements, serialize corresponding index values.
- [ ] **Step 3: Run regression tests.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/test_dat_table_values.py -q
  ```
  Expected result: All tests pass.

---

### Task 4: End-to-end integration with `Kemco_HA105.ACD` and SCADA export validation

**Files:**
- Modify: `tests/acd/test_dat_table_values.py`

- [ ] **Step 1: Add fixture validation tests on `Kemco_HA105.ACD`.**
  Convert `tests/acd/KemcoWaterHeater/Kemco_HA105.ACD` to L5X and assert:
  - `Alm_Store_Timer.PRE` equals `600000` (not `0`).
  - `Comm_CW_P1_Comms_Fail_Del.PRE` equals `3000` (not `0`).
  - `Comm_Comms_CW_P1_HZ_WData1_SCP1.InputMax` equals `80` (not `0`).
  - `Comm_Comms_CW_P1_HZ_WData1_SCP1.ScaledMax` equals `10000` (not `0`).
- [ ] **Step 2: Validate SCADA / Ignition exporter behavior.**
  Run `generate_ignition_tags` on the converted L5X and confirm analog scaling values are discovered accurately.
- [ ] **Step 3: Run full ACD test suite and MCP server smoke test.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/ -v
  PYTHONPATH=src python3 src/mcp_server/studio5000_mcp_server.py --test
  ```
  Expected result: All tests pass with zero regressions.
