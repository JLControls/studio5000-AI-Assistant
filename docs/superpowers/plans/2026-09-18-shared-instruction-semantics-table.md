# Shared Instruction Semantics Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one dependency-free instruction-semantics contract used by cross-reference, write detection, comment-graph edges, rung-structure parsing, and fast verification.

**Architecture:** Add `src/plc_instruction_semantics.py` as the neutral source of truth. It exposes `OperandRole`, immutable per-instruction read/write/control selectors, role/index helpers, `is_destructive`, and the known-instruction set. Existing consumers delegate to this module while retaining their current public result shapes; the duplicate verifier file is removed in favor of `src/verification/sdk_verifier.py`.

**Tech Stack:** Python 3.12, standard-library `enum`/`dataclasses`, existing RLL parser, pytest.

**Spec:** `docs/superpowers/ROADMAP.md` Phase 1 item 1 and §2; `docs/superpowers/plans/01-deterministic-ast-cross-reference.md` OperandRole contract.

**Status:** Implemented 2026-09-18. `.venv/bin/python -m pytest` reports 423 passed and 3 optional parity skips; the MCP `--test` diagnostic completes successfully.

## Global Constraints

- Keep public cross-reference result values JSON-compatible strings even when internal classification uses `OperandRole`.
- Unknown instructions remain unresolved and must not receive invented directional edges.
- Literal operands are excluded from graph edges and write maps.
- Preserve the existing `verification.sdk_verifier` import path; delete only the byte-identical `sdk_verifier_clean.py` duplicate.
- Do not modify proprietary PLC fixtures or add runtime/deployment claims to the roadmap.
- Use `.venv/bin/python -m pytest` for repository verification because it is Python 3.12.14.

---

### Task 1: Define the shared contract and regression tests

**Files:**
- Create: `src/plc_instruction_semantics.py`
- Test: `tests/test_plc_instruction_semantics.py`

**Interfaces:**
- `OperandRole(str, Enum)` values: `READ_SOURCE`, `WRITE_DESTINATION`, `READ_WRITE_CONTROL`, `AOI_INPUT`, `AOI_OUTPUT`, `AOI_INOUT`, `UNKNOWN`.
- `get_instruction_operand_role(mnemonic: str, operand_index: int, operand_count: int) -> OperandRole`.
- `get_operand_indices(mnemonic: str, operand_count: int) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]` returning read, write, and control indices.
- `is_destructive(mnemonic: str, operand_count: int | None = None) -> bool`.
- `is_known_instruction(mnemonic: str) -> bool` and `COMMON_INSTRUCTIONS: frozenset[str]`.

- [x] **Step 1: Write failing tests for enum values, operand roles, indices, destructiveness, and unknowns.**

```python
from plc_instruction_semantics import (
    COMMON_INSTRUCTIONS,
    OperandRole,
    get_instruction_operand_role,
    get_operand_indices,
    is_destructive,
    is_known_instruction,
)


def test_operand_role_values_are_json_safe():
    assert OperandRole.READ_SOURCE.value == "READ_SOURCE"
    assert OperandRole.WRITE_DESTINATION.value == "WRITE_DESTINATION"
    assert OperandRole.READ_WRITE_CONTROL.value == "READ_WRITE_CONTROL"
    assert OperandRole.AOI_INPUT.value == "AOI_INPUT"
    assert OperandRole.AOI_OUTPUT.value == "AOI_OUTPUT"
    assert OperandRole.AOI_INOUT.value == "AOI_INOUT"
    assert OperandRole.UNKNOWN.value == "UNKNOWN"


def test_shared_table_classifies_core_operand_roles():
    assert get_instruction_operand_role("XIC", 0, 1) is OperandRole.READ_SOURCE
    assert get_instruction_operand_role("OTE", 0, 1) is OperandRole.WRITE_DESTINATION
    assert get_instruction_operand_role("ONS", 0, 1) is OperandRole.READ_WRITE_CONTROL
    assert get_instruction_operand_role("MOV", 0, 2) is OperandRole.READ_SOURCE
    assert get_instruction_operand_role("MOV", 1, 2) is OperandRole.WRITE_DESTINATION
    assert get_instruction_operand_role("ADD", 2, 3) is OperandRole.WRITE_DESTINATION
    assert get_instruction_operand_role("TON", 0, 3) is OperandRole.WRITE_DESTINATION
    assert get_instruction_operand_role("RES", 0, 1) is OperandRole.WRITE_DESTINATION
    assert get_instruction_operand_role("SCP", 5, 6) is OperandRole.WRITE_DESTINATION


def test_shared_table_resolves_last_operand_and_destructive_state():
    assert get_operand_indices("ADD", 3) == ((0, 1), (2,), ())
    assert get_operand_indices("COP", 3) == ((0,), (1,), ())
    assert get_operand_indices("ONS", 1) == ((), (), (0,))
    assert is_destructive("OTE") is True
    assert is_destructive("TON") is True
    assert is_destructive("ONS") is True
    assert is_destructive("XIC") is False


def test_unknown_instruction_has_no_direction_or_destructive_effect():
    assert get_instruction_operand_role("CUSTOM_AOI", 0, 2) is OperandRole.UNKNOWN
    assert get_operand_indices("CUSTOM_AOI", 2) == ((), (), ())
    assert is_destructive("CUSTOM_AOI") is False
    assert is_known_instruction("CUSTOM_AOI") is False
    assert "MOV" in COMMON_INSTRUCTIONS
```

- [x] **Step 2: Run the focused test to verify it fails for the missing module.**

Run: `.venv/bin/python -m pytest tests/test_plc_instruction_semantics.py -q`

Expected: collection fails because `plc_instruction_semantics` does not exist.

- [x] **Step 3: Implement the minimal immutable table and helpers.**

Use integer operand selectors, with `-1` meaning the last supplied operand. Store read, write, and control selectors separately. The role helper checks control first, then writes, then reads; malformed/out-of-range indices return `UNKNOWN`. Populate the table with the current `_role_for` and `_DIRECTION` coverage plus the existing verifier’s `COMMON_INSTRUCTIONS` set, including `COP`, `CPS`, `BTD`, `SSV`, `GSV`, and long-form neutral-text spellings.

- [x] **Step 4: Run the focused test to verify it passes.**

Run: `.venv/bin/python -m pytest tests/test_plc_instruction_semantics.py -q`

Expected: all focused semantics tests pass.

---

### Task 2: Migrate the four semantics consumers

**Files:**
- Modify: `src/l5x_analyzer/tag_cross_reference.py`
- Modify: `src/l5x_analyzer/write_analyzer.py`
- Modify: `src/comment_graph/edges.py`
- Modify: `src/comment_graph/builder.py`
- Modify: `src/tag_analyzer/comment_pipeline.py`
- Modify: `src/verification/sdk_verifier.py`
- Test: `tests/test_write_analyzer.py`
- Test: `tests/comment_graph/test_edges.py`

**Interfaces:**
- Cross-reference `_role_for` delegates to `get_instruction_operand_role` and serializes `OperandRole.value`.
- Write analysis uses balanced `find_calls` plus shared write/control indices and retains AOI output handling and location records.
- Edge extraction uses `get_operand_indices`; unknown instructions still produce unresolved `REFERENCES` edges.
- Rung-structure output classification uses `is_destructive` instead of a private output list.
- The verifier re-exports `COMMON_INSTRUCTIONS` from the shared module for compatibility; `comment_graph.builder` imports the shared module directly.

- [x] **Step 1: Add failing integration assertions for COP writes and shared destructive classification.**
- [x] **Step 2: Run the focused tests and confirm the pre-migration failure.**
- [x] **Step 3: Replace local role/direction/output tables with shared helper calls.**
- [x] **Step 4: Run focused cross-reference, write-analyzer, comment-graph, and tag-pipeline tests.**

Run: `.venv/bin/python -m pytest tests/test_plc_instruction_semantics.py tests/test_write_analyzer.py tests/comment_graph/test_edges.py tests/l5x_analyzer/test_tag_cross_reference.py -q`

Expected: all selected tests pass with no unknown-instruction regression.

---

### Task 3: Remove verifier duplication and reconcile documentation

**Files:**
- Delete: `src/verification/sdk_verifier_clean.py`
- Modify: `README.md`
- Modify: `docs/ENGINEERING_AUDIT_2026.md`
- Modify: `docs/superpowers/plans/05-plc-static-analysis-linter.md`
- Modify: `docs/superpowers/specs/05-plc-static-analysis-linter.md`
- Modify: `docs/superpowers/ROADMAP.md`

- [x] **Step 1: Remove references to the deleted clean-verifier path and state that `sdk_verifier.py` is canonical.**
- [x] **Step 2: Mark Phase 1 item 1 as delivered, update the cross-cutting dependency wording, remove the stale duplicate-table inventory, and record the verified `.venv` test baseline in `ROADMAP.md`.**
- [x] **Step 3: Run documentation link/path searches and `git diff --check`.**

Run: `git grep -n "sdk_verifier_clean\|four operand-role tables" -- ':!docs/superpowers/plans/2026-09-18-shared-instruction-semantics-table.md'` and `git diff --check`

Expected: no stale source/documentation references remain except historical audit text explicitly labeled as historical, and the diff has no whitespace errors.

---

### Task 4: Full verification and handoff

- [x] **Step 1: Run the complete Python 3.12 test suite.**

Run: `.venv/bin/python -m pytest`

- [x] **Step 2: Run the internal MCP server diagnostic.**

Run: `.venv/bin/python src/mcp_server/studio5000_mcp_server.py --test`

- [x] **Step 3: Inspect the final diff and status.**

Run: `git diff --stat`, `git diff --check`, and `git status --short`

- [x] **Step 4: Report exact test results, files changed, and any runtime/deployment validation that remains outside this offline change.**
