# ACD `patch_rungs` `@HEX@` Substitution for Newly Introduced Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Partial implementation. The current writer already builds a global name map and performs token-aware substitution; this plan must finish nested-operand parsing, strict-vs-advisory validation, and compressed binary round-trip guarantees.

**Goal:** Fix `_restore_tag_refs` in `src/acd/zip/write_dat.py` so that any recognized project tag introduced into a modified ladder rung is correctly substituted with its `@HEX_OBJECT_ID@` handle in `SbRegion.Dat`, with opcode-safe tokenization, member/array preservation, and auditable handling of unknown tags.

**Architecture:** Replace the localized rung-scoped tag substitution with a robust tokenizer and global inverted tag map (`{name: object_id}`). Tokenize ladder logic into mnemonic opcodes and operand argument lists (`OPCODE(arg1, arg2, ...)`), substitute tag names strictly in operand positions matching word boundaries, preserve sub-element paths (e.g. `.PRE`, `[0]`), and safely handle tags with overlapping substrings. Integrate with `patch_sbregion_dat` and `src/acd/api.py:patch_rungs`.

**Tech Stack:** Python 3.12, regex tokenization, binary struct packing, SQLite / ACD object model, pytest.

---

## Global Constraints

- Never mutate untouched rungs or modify `SbRegion.Dat` headers/trailers incorrectly; `file_length` and `number_records_fafa` must match Kaitai Dat formulas.
- Never replace ladder instruction opcodes (e.g., `XIC`, `OTE`, `TON`, `MOV`, `ADD`, `SUB`, `COP`, `CPT`) or Logix keywords with tag IDs.
- Invert the full `id_to_name` project mapping (`{name: object_id}`) rather than filtering by tokens present in the original rung text.
- Sort substitution candidate tags longest-first (`key=len, reverse=True`) to prevent prefix collisions (e.g., `Motor_101_Run_Feedback` vs `Motor_101_Run`).
- Sub-element references (e.g., `Tag.PRE`, `Tag.ACC`, `ArrayTag[2]`, `StructTag.Member.SubMember`) must substitute only the base tag identifier (e.g., `@HEX@.PRE`, `@HEX@[2]`).
- Pre-existing `@HEX@` tokens in input strings must remain untouched.
- If a rung references a tag that does not exist in `id_to_name`, use an explicit strict/advisory policy. Strict mode may reject an unresolved operand only after the tokenizer has classified it as a tag position; advisory mode must return the unresolved token in diagnostics. Unknown identifiers in literals, strings, AOI names, or unsupported instructions are not automatically tag errors.
- **Binary round-trip:** preserve whether the source `SbRegion.Dat` was gzip-compressed and restore that representation after patching. A no-op patch must be byte-identical at the archive-entry level.
- All tests must pass with `PYTHONPATH=src python3 -m pytest tests/acd/`.

## Review gates before implementation

- The parser must scan balanced instruction calls and nested brackets/parentheses; the sketch `re.sub(r'([A-Za-z0-9_]+)\\(([^)]*)\\)', ...)` is not a valid implementation because it truncates nested operands and can rewrite text inside literals.
- Keep `known_opcodes` and `strict` separate: opcode recognition controls parsing, while strictness controls unresolved operand diagnostics. Do not treat every unknown mnemonic as a missing tag.
- Validate `FAFA` record counts, lengths, and the original compression flag before allocating a replacement payload. Fail before writing when validation is ambiguous.

---

## File Map

Create:
- `tests/acd/test_patch_rungs_hex.py` — comprehensive unit tests for `_restore_tag_refs`, opcode collisions, prefix shadowing, member paths, array indexing, and `patch_sbregion_dat`.

Modify:
- `src/acd/zip/write_dat.py` — reimplement `_restore_tag_refs` with tokenizer, opcode protection, global name-to-hex substitution, and validation.
- `src/acd/api.py` — export `TagNotFoundError` (or related exceptions) and add tag validation docstrings to `patch_rungs`.
- `tests/acd/test_regn_link.py` — verify backwards compatibility with existing regression tests.

Do not modify:
- `tests/test_direct_acd_deliverables.py` (user worktree change).
- Unrelated Kaitai generated parsers under `src/acd/generated/`.

---

### Task 1: Build comprehensive failing unit tests for `@HEX@` substitution

**Files:**
- Create: `tests/acd/test_patch_rungs_hex.py`

**Interfaces:**
```python
def _restore_tag_refs(
    new_text: str,
    orig_text_with_refs: str,
    id_to_name: Dict[int, str],
    known_opcodes: Optional[set[str]] = None,
    strict: bool = False,
) -> str: ...
```

- [ ] **Step 1: Write test cases covering all substitution mechanics and edge cases.**
  Create `tests/acd/test_patch_rungs_hex.py` with test cases:
  1. `test_substitute_newly_introduced_tag`: Rung original has `XIC(@10@)OTE(@20@);`. New rung introduces tag `New_Interlock` (ID `0x30`), outputting `XIC(@10@)XIO(@30@)OTE(@20@);`.
  2. `test_opcode_protection_single_letter_tag`: Project has a tag named `X` (ID `0x50`) or `TON` (ID `0x60`). Ensure `XIC(MyTag)` does not become `@50@IC(MyTag)` and `TON(Timer1, ?, ?)` does not become `@60@(Timer1, ?, ?)`.
  3. `test_substring_collision_longest_first`: Tags `Pump1` (ID `0x101`) and `Pump10` (ID `0x10A`). A rung with `XIC(Pump10)` must become `XIC(@10A@)`, NOT `XIC(@101@0)`.
  4. `test_member_and_array_access`: `Timer1.PRE` (ID `0x200`) -> `@200@.PRE`, `Buffer[5]` (ID `0x300`) -> `@300@[5]`, `VFD.Status.Running` (ID `0x400`) -> `@400@.Status.Running`.
  5. `test_preserve_existing_hex_tokens`: A rung already containing `XIC(@0625AD82@)` must not alter the `@0625AD82@` token.
  6. `test_unrecognized_tag_handling`: A rung introducing `NonExistent_Tag` not in `id_to_name` raises `TagNotFoundError` (or handled per configuration).
  7. `test_complex_branching_ladder_logic`: Nested branches `[XIC(TagA) , [XIC(TagB) , XIC(TagC)] ] OTE(TagD);` correctly replaces all operands without breaking branch brackets `[,]`.

  ```python
  import pytest
  from acd.zip.write_dat import _restore_tag_refs, TagNotFoundError

  def test_substitute_newly_introduced_tag():
      id_to_name = {
          0x10: "Existing_Tag",
          0x20: "Output_Coil",
          0x30: "New_Interlock",
      }
      orig_text = "XIC(@10@)OTE(@20@);"
      new_text = "XIC(Existing_Tag)XIO(New_Interlock)OTE(Output_Coil);"

      result = _restore_tag_refs(new_text, orig_text, id_to_name)
      assert result == "XIC(@10@)XIO(@30@)OTE(@20@);"
      assert "New_Interlock" not in result
  ```

- [ ] **Step 2: Run pytest to inspect test failures.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/test_patch_rungs_hex.py -q
  ```
  Expected result: Failures on tests expecting `TagNotFoundError` or complex nested member/token syntax.

---

### Task 2: Implement robust opcode-safe `_restore_tag_refs` in `src/acd/zip/write_dat.py`

**Files:**
- Modify: `src/acd/zip/write_dat.py`

- [ ] **Step 1: Define `TagNotFoundError` and common Logix instruction opcode sets.**
  Add standard Studio 5000 instruction opcodes (bit, timer/counter, math, compare, move/logical, program control) to a protected set so they are never treated as operand tokens.

  ```python
  class TagNotFoundError(ValueError):
      """Raised when rung text references a tag not found in the ACD project."""
      pass

  _COMMON_LOGIX_OPCODES = frozenset({
      "XIC", "XIO", "OTE", "OTL", "OTU", "ONS", "OSR", "OSF",
      "TON", "TOF", "RTO", "CTU", "CTD", "RES",
      "EQU", "NEQ", "LES", "LEQ", "GRT", "GEQ", "LIM", "MEQ",
      "ADD", "SUB", "MUL", "DIV", "MOD", "SQR", "NEG", "ABS",
      "MOV", "MVM", "COP", "CPS", "FLL", "CLR", "BTD",
      "AND", "OR", "XOR", "NOT",
      "JMP", "LBL", "JSR", "RET", "SBR", "TND", "MCR",
      "PID", "ALMD", "ALMA", "MSG", "GSV", "SSV",
  })
  ```

- [ ] **Step 2: Implement the operand-level tokenization and substitution algorithm.**
  In `_restore_tag_refs`:
  1. Build global `name_to_hex = {name: f"@{oid:X}@" for oid, name in id_to_name.items() if name}`.
  2. Parse the ladder rung text into instruction calls `OPCODE(...)` and structural delimiters `[ , ] ;`.
  3. Inside the operand argument parentheses `(...)`, split operands by comma (respecting nested expressions/brackets).
  4. For each operand token:
     - Check if it is already an `@HEX@` token (`@...HEX...@`).
     - Separate the base tag name from member access (`.Field`) or array subscript (`[i]`).
     - Match the base tag against `name_to_hex` (longest-first).
     - If matched, replace base tag with `@HEX@` and re-attach `.Field` / `[i]`.
     - If base tag is not in `name_to_hex` and is not a numeric literal / keyword, raise `TagNotFoundError` or format appropriately.
  5. Rebuild the rung string.

  ```python
  def _restore_tag_refs(
      new_text: str,
      orig_text_with_refs: str,
      id_to_name: Dict[int, str],
      known_opcodes: Optional[set[str]] = None,
      strict: bool = False,
  ) -> str:
      del orig_text_with_refs
      if not id_to_name:
          return new_text

      name_to_id = {
          name: oid for oid, name in id_to_name.items()
          if isinstance(name, str) and name and not name.startswith("@")
      }
      if not name_to_id:
          return new_text

      # Match instruction calls: OPCODE(arg1, arg2, ...)
      def replace_instruction(match: re.Match[str]) -> str:
          opcode = match.group(1)
          args_str = match.group(2)

          # Process comma-separated arguments
          args = [a.strip() for a in _split_rung_args(args_str)]
          new_args = []
          for arg in args:
              new_args.append(_substitute_operand(arg, name_to_id, strict=strict))
          return f"{opcode}({', '.join(new_args)})"

      return _scan_instruction_calls(new_text, replace_instruction, known_opcodes=known_opcodes)
  ```

- [ ] **Step 3: Run unit tests and verify all pass.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/test_patch_rungs_hex.py -q
  ```
  Expected result: All unit tests pass.

---

### Task 3: Integrate with `patch_sbregion_dat` and `src/acd/api.py`

**Files:**
- Modify: `src/acd/zip/write_dat.py`
- Modify: `src/acd/api.py`

- [ ] **Step 1: Ensure `patch_sbregion_dat` passes `id_to_name` properly and handles errors cleanly.**
  Verify `patch_sbregion_dat` catches invalid rung syntax or unknown tag references before byte reallocation occurs.
- [ ] **Step 2: Update `src/acd/api.py:patch_rungs` docstrings and error exports.**
  Expose `TagNotFoundError` from `acd.api` so callers can catch it when submitting invalid edits.
- [ ] **Step 3: Verify existing `tests/acd/test_regn_link.py` passes without regressions.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/test_regn_link.py -q
  ```
  Expected result: All tests pass.

---

### Task 4: End-to-end integration and fixture roundtrip verification

**Files:**
- Modify: `tests/acd/test_patch_rungs_hex.py`

- [ ] **Step 1: Add end-to-end test using `Kemco_HA105.ACD`.**
  Load `tests/acd/KemcoWaterHeater/Kemco_HA105.ACD`, patch a routine rung with a tag from another routine/scope, save to a temporary `.ACD` file, reload with `load_acd`, and verify the patched rung text is identical to the input plaintext string while the raw `SbRegion.Dat` record contains valid `@HEX@` tokens.
- [ ] **Step 2: Run the full ACD test suite and MCP server smoke test.**
  Run:
  ```bash
  PYTHONPATH=src python3 -m pytest tests/acd/ -v
  PYTHONPATH=src python3 src/mcp_server/studio5000_mcp_server.py --test
  ```
  Expected result: All tests pass with zero regressions.
