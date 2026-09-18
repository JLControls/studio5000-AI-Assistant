# Direct ACD Comment Writer (`patch_comments`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Backlog with a binary-safety blocker. The record layout is a hypothesis until it is validated against tracked golden bytes and a real Studio 5000 round trip.

**Goal:** Implement direct, offline writing of tag-level and operand descriptions into Rockwell `.ACD` binary container `Comments.Dat` streams, allowing `generate_comment_deliverables` and `analyze_comment_graph` with `edit_acd=True` to emit an updated `.ACD` file natively populated with documentation.

**Architecture:** Build a `Comments.Dat` binary record patcher (`patch_comments_dat` in `src/acd/zip/write_dat.py`) modeled after `patch_sbregion_dat`. The patcher decompresses the DAT stream, parses the 24-byte DAT header, linearly iterates `0xFAFA` records, updates existing Type-1 (`AsciiRecord`) tag descriptions or appends new Type-1 records (derived from a verified template record) for previously uncommented tags, recalculates `file_length` and `number_records_fafa`, and preserves the binary trailer verbatim. Expose this via `patch_comments(project, comment_map)` in `src/acd/api.py` and wire into `src/tag_analyzer/comment_pipeline.py`.

**Tech Stack:** Python 3.12, struct binary layout packing/unpacking, gzip, `Unzip`, `write_acd`, `CommentsRecord`, `PLCCommentPipeline`, pytest.

---

## Global Constraints

- Preserve byte-identical roundtrips when `tag_descriptions` is empty (`Unzip` → `build_acd_bytes` produces exact original bytes).
- Do not mutate or invalidate unrelated `0xFAFA` record types (e.g., Type 11 operand comments, Type 12 UDI history records, Types 3–8/13/14).
- Container headers must accurately update:
  - `file_length`: `first_record_position + len(new_records) - 1`
  - `number_records_fafa`: count of all `0xFAFA` records written (existing + newly appended).
- Trailer after `file_length + 1` (FEFE pointer tables) must be copied verbatim only after pointer-table bounds are parsed and proven independent of changed record lengths; otherwise update pointers from a verified fixture.
- In-place modification of existing Type-1 records must dynamically update `len_record` (container level) and `record_length` / `sub_record_length` (record header level) to accommodate variable-length UTF-8 text strings.
- Appended Type-1 records must use a valid Type-1 binary template structure:
  - Container header: `identifier = 0xFAFA (u16)`, `len_record = 6 + payload_len (u32)`
  - Payload header (10 bytes): `seq_number (u16)`, `record_type = 1 (u16)`, `sub_record_length = payload_len - 10 (u16)`, `parent = 0 (u32)`
  - Body: `unknown_1[13]`, `object_id (u32)`, `unknown_2[13]`, `record_string (UTF-8, null-terminated)`
- Integrate directly with `src/tag_analyzer/comment_pipeline.py` so `edit_acd=True` commits a normalized canonical decision (`NAME` plus `PROPOSED_DESCRIPTION`, with explicit type/scope) without requiring separate CSV import steps. Reject unknown or ambiguous decisions before mutation; do not partially write a subset and report success.
- All tests must pass with `PYTHONPATH=src python3 -m pytest tests/acd/`.

## Review gates before implementation

- The sample header currently has a concrete arity bug: `struct.pack("<IHHI", payload_len, seq_number, 1, sub_record_length, 0)` supplies five values to a four-field format. Use a five-field format such as `"<IHHHI"` only after the byte layout is confirmed by a fixture.
- Preserve and restore the source compression state (`gzip` versus raw bytes), and keep `project._raw_files`/archive-entry semantics distinct from the decompressed parser buffer.
- Require unchanged-input no-op, existing-record update, append, and reparse tests before wiring `edit_acd=True` into the comment pipeline.

---

## File Map

Create:
- `tests/acd/test_comments_writer.py` — unit and integration tests for `patch_comments_dat`, modifying existing descriptions, appending new tag descriptions, round-trip fidelity, and L5X description export validation.

Modify:
- `src/acd/zip/write_dat.py` — implement `patch_comments_dat`, `_build_type1_comment_record`, and record iterator helpers.
- `src/acd/api.py` — add `patch_comments(project: RSLogix5000Content, comment_map: Dict[str, str]) -> None`.
- `src/tag_analyzer/comment_pipeline.py` — update `generate_deliverables` direct ACD editing branch to extract tag descriptions from decisions and call `patch_comments`.
- `src/tag_analyzer/tag_mcp_integration.py` — verify deliverables response returns `updated_acd` with comments written.

Do not modify:
- `tests/test_direct_acd_deliverables.py` (pre-existing worktree modification).
- Unrelated Kaitai generated parsers under `src/acd/generated/`.

---

### Task 1: Build failing unit tests for `Comments.Dat` record patching

**Files:**
- Create: `tests/acd/test_comments_writer.py`

**Interfaces:**
```python
def patch_comments_dat(
    dat_bytes: bytes,
    tag_descriptions: Dict[int, str],
    template_record_bytes: Optional[bytes] = None,
) -> bytes: ...

def patch_comments(
    project: RSLogix5000Content,
    comment_map: Dict[str, str],
) -> None: ...
```

- [ ] **Step 1: Write test cases covering `Comments.Dat` binary manipulation.**
  Create `tests/acd/test_comments_writer.py` containing:
  1. `test_roundtrip_unmodified_comments_dat`: Uncompressed `Comments.Dat` passed with empty changes produces identical output bytes.
  2. `test_modify_existing_type1_comment`: Load `Comments.Dat` from `Kemco_HA105.ACD`, find an existing Type-1 record (e.g. tag `Alm_Store_Timer` or similar), patch its description text to `"Updated Unit Test Description"`. Re-parse with `CommentsRecord.parse` and assert the new text is returned.
  3. `test_append_new_type1_comment`: Take a tag with no existing comment in `Kemco_HA105.ACD`, supply `{tag_object_id: "Brand New Description"}`. Assert that `number_records_fafa` increases by 1, and `CommentsRecord.parse` parses the newly added record successfully.
  4. `test_patch_comments_api`: Test `patch_comments(project, {"Com_HWT1_Temp": "Hot Water Tank Temp Sensor"})` via high-level API.
  5. `test_l5x_conversion_reflects_patched_comment`: Convert patched project to L5X (`ConvertAcdToL5x`) and assert `<Tag Name="Com_HWT1_Temp">` has `<Description><![CDATA[Hot Water Tank Temp Sensor]]></Description>`.

  ```python
  import pytest
  from acd.api import load_acd, patch_comments
  from acd.zip.write_dat import patch_comments_dat
  from acd.record.comments import CommentsRecord
  from acd.database.dbextract import DatRecord

  def test_modify_existing_type1_comment():
      # Load fixture, extract Comments.Dat
      # Patch known object_id
      # Validate re-parsed records
      pass
  ```

- [ ] **Step 2: Run pytest to inspect test failures.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/test_comments_writer.py -q
  ```
  Expected result: Failures because `patch_comments_dat` and `patch_comments` do not yet exist.

---

### Task 2: Implement `patch_comments_dat` in `src/acd/zip/write_dat.py`

**Files:**
- Modify: `src/acd/zip/write_dat.py`

- [ ] **Step 1: Define Type-1 record layout constants and helper structures.**
  Add offsets and builder functions for Type-1 FAFA comment records:

  ```python
  # Offsets in Type-1 FAFA payload:
  # [0:4] record_length u32
  # [4:6] seq_number u16
  # [6:8] record_type u16 (= 0x0001)
  # [8:10] sub_record_length u16
  # [10:14] parent u32
  # [14:27] unknown_1 (13 bytes)
  # [27:31] object_id u32
  # [31:44] unknown_2 (13 bytes)
  # [44:] record_string (UTF-8, null-terminated)

  def _is_type1_comment_record(payload: bytes) -> bool:
      if len(payload) < 45:
          return False
      rec_type = struct.unpack_from("<H", payload, 6)[0]
      return rec_type in (1, 2)

  def _get_type1_object_id(payload: bytes) -> int:
      return struct.unpack_from("<I", payload, 27)[0]

  def _build_type1_comment_record(
      object_id: int,
      description: str,
      seq_number: int,
      template_payload: Optional[bytes] = None,
  ) -> bytes:
      text_bytes = description.encode("utf-8") + b"\x00"
      if template_payload and len(template_payload) >= 44:
          unknown_1 = template_payload[14:27]
          unknown_2 = template_payload[31:44]
      else:
          unknown_1 = b"\x00" * 13
          unknown_2 = b"\x00" * 13

      body = unknown_1 + struct.pack("<I", object_id) + unknown_2 + text_bytes
      sub_record_length = len(body)
      payload_len = 10 + sub_record_length
      header = struct.pack("<IHHHI", payload_len, seq_number, 1, sub_record_length, 0)
      payload = header + body
      return struct.pack("<HI", _FAFA, 6 + len(payload)) + payload
  ```

- [ ] **Step 2: Implement `patch_comments_dat`.**
  Decompress input if gzipped, parse fixed header, iterate records, update matching Type-1 records, track untouched object IDs, append remaining new records, recalculate `file_length` and `number_records_fafa`, and return assembled bytes with trailer.

  ```python
  def patch_comments_dat(
      dat_bytes: bytes,
      tag_descriptions: Dict[int, str],
      template_record_bytes: Optional[bytes] = None,
  ) -> bytes:
      if not tag_descriptions:
          return dat_bytes

      if dat_bytes[:2] == b"\x1f\x8b":
          dat_bytes = gzip.decompress(dat_bytes)

      (format_type, blank_2, _file_length, first_record_pos,
       blank_3, num_fafa) = struct.unpack_from("<IIIIII", dat_bytes, 0)

      header_verbatim = dat_bytes[:first_record_pos]
      records_end = _file_length + 1
      trailer = dat_bytes[records_end:]

      pos = first_record_pos
      new_records = bytearray()
      new_num_fafa = 0
      pending_descriptions = dict(tag_descriptions)
      template_payload = None

      while pos < records_end:
          identifier = struct.unpack_from("<H", dat_bytes, pos)[0]
          len_record = struct.unpack_from("<I", dat_bytes, pos + 2)[0]
          payload = dat_bytes[pos + 6 : pos + len_record]

          if identifier == _FAFA:
              new_num_fafa += 1
              if _is_type1_comment_record(payload):
                  template_payload = payload
                  oid = _get_type1_object_id(payload)
                  if oid in pending_descriptions:
                      new_desc = pending_descriptions.pop(oid)
                      seq = struct.unpack_from("<H", payload, 4)[0]
                      new_records.extend(_build_type1_comment_record(oid, new_desc, seq, payload))
                      pos += len_record
                      continue

          new_records.extend(dat_bytes[pos : pos + len_record])
          pos += len_record

      # Append newly introduced tag comments
      seq_counter = new_num_fafa + 1
      for oid, new_desc in pending_descriptions.items():
          new_records.extend(
              _build_type1_comment_record(oid, new_desc, seq_counter, template_payload)
          )
          seq_counter += 1
          new_num_fafa += 1

      new_file_length = first_record_pos + len(new_records) - 1
      new_header = bytearray(header_verbatim)
      struct.pack_into("<I", new_header, 8, new_file_length)
      struct.pack_into("<I", new_header, 20, new_num_fafa)

      return bytes(new_header) + bytes(new_records) + trailer
  ```

- [ ] **Step 3: Run unit tests and verify `patch_comments_dat` passes.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/test_comments_writer.py -k test_modify_existing_type1_comment -q
  ```
  Expected result: Passes.

---

### Task 3: Implement `patch_comments` in `src/acd/api.py`

**Files:**
- Modify: `src/acd/api.py`

- [ ] **Step 1: Implement `patch_comments(project, comment_map)`.**
  Map human tag names in `comment_map` (`{tag_name: description}`) to integer `object_id`s using `project._id_to_name` (inverting to `{name: object_id}`). Invoke `patch_comments_dat` on `project._raw_files["Comments.Dat"]`.

  ```python
  def patch_comments(project: RSLogix5000Content, comment_map: Dict[str, str]) -> None:
      """Patch tag descriptions in a loaded project's Comments.Dat in-place.

      Args:
          project: Project loaded by load_acd().
          comment_map: Mapping of {tag_name: description_text}.
      """
      if not comment_map:
          return

      name_to_id = {
          name: oid for oid, name in project._id_to_name.items()
          if isinstance(name, str) and name
      }

      tag_descriptions: Dict[int, str] = {}
      for tag_name, desc in comment_map.items():
          if tag_name in name_to_id:
              tag_descriptions[name_to_id[tag_name]] = desc
          else:
              logger.warning(f"Cannot patch comment for unknown tag: {tag_name}")

      if tag_descriptions:
          project._raw_files["Comments.Dat"] = patch_comments_dat(
              project._raw_files["Comments.Dat"],
              tag_descriptions,
          )
  ```

- [ ] **Step 2: Run API tests.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/test_comments_writer.py -k test_patch_comments_api -q
  ```
  Expected result: Passes.

---

### Task 4: Integrate comment writing into `PLCCommentPipeline` (`edit_acd=True`)

**Files:**
- Modify: `src/tag_analyzer/comment_pipeline.py`

- [ ] **Step 1: Extract tag-level comments from decisions and call `patch_comments`.**
  In `comment_pipeline.py:generate_deliverables` (around line 440):
  When `edit_acd or target_acd` is active:
  1. Normalize the canonical decision fields (`NAME` plus `PROPOSED_DESCRIPTION`) and accept legacy aliases only through a validated adapter.
  2. If comment decisions exist, build `comment_map = {tag_name: comment_text}` and call `patch_comments(proj, comment_map)`.
  3. If rung changes also exist (`PROPOSED_RUNG_TEXT`), call `patch_rungs(proj, rung_changes)`.
  4. Save project via `save_acd(proj, str(updated_acd_path))`.

  ```python
  # In comment_pipeline.py
  from acd.api import load_acd, patch_rungs, patch_comments, save_acd

  comment_map: Dict[str, str] = {}
  for dec in decisions:
      tag_name = dec.get("NAME")
      comment_text = dec.get("PROPOSED_DESCRIPTION")
      if tag_name and comment_text and not dec.get("PROPOSED_RUNG_TEXT"):
          comment_map[str(tag_name)] = str(comment_text)

  if comment_map:
      patch_comments(proj, comment_map)
  ```

- [ ] **Step 2: Add integration tests for `generate_deliverables(edit_acd=True)`.**
  Verify that when `edit_acd=True`, the generated `_updated.ACD` has `Comments.Dat` modified and containing the new tag descriptions.

---

### Task 5: Verification and round-trip safety validation

**Files:**
- Run: `tests/acd/test_comments_writer.py`
- Run: `src/mcp_server/studio5000_mcp_server.py --test`

- [ ] **Step 1: Run complete ACD test suite.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/ -v
  ```
  Expected result: All tests pass.

- [ ] **Step 2: Run MCP server smoke test.**
  Run:
  ```bash
  PYTHONPATH=src python3 src/mcp_server/studio5000_mcp_server.py --test
  ```
  Expected result: Server smoke tests pass.
