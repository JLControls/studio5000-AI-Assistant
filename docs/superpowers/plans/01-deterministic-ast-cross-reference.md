# Deterministic AST Tag Cross-Reference Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Partial implementation. The current tree already has deterministic relationship lookup and project-structure inspection; this plan is the delta for API completeness, richer operand coverage, and bounded fixture evidence.

**Goal:** Implement a deterministic AST-based cross-reference and "where-used" engine (`find_tag_references`) for Rockwell Studio 5000 projects (.L5X and .ACD), classifying references by operational role and replacing broken vector-based search wrappers.

**Architecture:** Build upon exact AST structural token parsing across RLL and ST routines. Parse L5X XML (and transparently convert offline ACD files via `acd_offline_convert`), extract controller and program symbol tables with alias-chain resolution, tokenize ladder rungs with balanced parenthesis extraction, tokenize Structured Text expressions, bind Add-On Instruction (AOI) definitions to classify parameter usage (`Input`, `Output`, `InOut`), and categorize standard Studio 5000 instructions through deterministic static role tables. Expose this engine via MCP tool `find_tag_references` and wire legacy wrappers `find_related_components` and `find_related_tags` to delegate directly to this deterministic engine.

**Tech Stack:** Python 3.12, XML ElementTree, standard library `re` and `dataclasses`, `l5x_analyzer` AST utilities (`rll_parser`, `aoi_logic_inspector`, `acd_offline_convert`), MCP JSON-RPC protocol, pytest.

---

## Global Constraints

- **Zero Vector Lookups / Zero Probabilities:** Tag lookup must match exact identifier tokens. No FAISS queries, embeddings, cosine similarity thresholds, or synthetic search prompts (`"uses {tag}"`).
- **Deterministic Scope Disambiguation:** Program-scoped tags and controller-scoped tags with identical names must not collide. Ambiguous queries across scopes must fail fast with clear diagnostic messages unless `program_scope` is supplied.
- **Sub-Element Matching Precision:** Support `match_sub_elements` (default `True`). Searching `Htr1` matches `Htr1.Sts.Running`, `Htr1.Cmd`, `Htr1[0]`. When `match_sub_elements=False`, only exact token matches are returned.
- **Alias Resolution:** Aliases defined via `AliasFor` must resolve through multi-level alias chains to their terminal target while preserving the source operand in the reference record.
- **Performance Budget:** Measure parse/index/query timings separately on representative synthetic and optional real fixtures. Do not make a universal `<250ms` promise until the fixture, hardware, Python version, and cache state are recorded; query latency must not be confused with first-ingest latency.
- **Engineering Review Requirement:** Output must explicitly indicate that where-used results are static offline analysis and require verification against Studio 5000 Logix Designer v36+ before live operations.

## Review gates before implementation

- Treat the existing public `find_tag_references(path, tag_name, program_scope=None)` and its current role strings as compatibility surface. Add `match_sub_elements` and richer records additively, or provide an explicit versioned adapter; do not silently break `find_related_tags` callers.
- Put operand roles, output semantics, scope identity, and unresolved-instruction handling in one shared table/module used by the linter and comment graph. Plan-01 must not create a second authoritative copy.
- A converted ACD result is a derived artifact. Return conversion warnings and source provenance with the report; never present it as lossless L5X analysis.
- Use a tracked synthetic L5X fixture for deterministic CI evidence. Optional proprietary fixtures may strengthen performance/ACD coverage but must produce a visible skip, not a claimed pass, when absent.

---

## File Map

### Create:
- `tests/l5x_analyzer/test_deterministic_cross_reference.py` — Dedicated test suite covering comprehensive instruction role classifications, AOI parameter mapping, ST assignment expressions, alias chains, sub-element matching flags, ACD offline ingestion, and MCP schema/dispatch.
- `tests/l5x_analyzer/fixtures/cross_ref_sample.L5X` — Synthetic L5X fixture exercising all instruction categories, AOI calls, multi-program scope, and Structured Text lines.

### Modify:
- `src/l5x_analyzer/tag_cross_reference.py` — Update data models to strict `OperandRole` enum and `TagReference`/`TagReferenceReport` dataclasses, implement complete standard instruction mapping table, enhance ST assignment parsing, support `match_sub_elements`, and add transparent `.ACD` file ingestion via `convert_acd_to_l5x`.
- `src/l5x_analyzer/l5x_mcp_integration.py` — Update `find_tag_references` signature to accept `match_sub_elements`, route `.ACD` paths, and ensure `find_related_components` delegates to the deterministic report.
- `src/tag_analyzer/tag_mcp_integration.py` — Update `find_related_tags` to delegate to deterministic L5X cross-reference when project logic is available.
- `src/mcp_server/studio5000_mcp_server.py` — Update tool registration, JSON-RPC handler signature, and `tools/list` schema for `find_tag_references`.
- `tests/l5x_analyzer/test_tag_cross_reference.py` — Update existing unit tests for new `OperandRole` enum values and data structures.

### Do Not Modify:
- `tests/test_direct_acd_deliverables.py` (pre-existing worktree modification).
- Core parsing internals of `src/acd/` (vendored parser).

---

## Data Models & Type Specifications

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

class OperandRole(str, Enum):
    READ_SOURCE = "READ_SOURCE"
    WRITE_DESTINATION = "WRITE_DESTINATION"
    READ_WRITE_CONTROL = "READ_WRITE_CONTROL"
    AOI_INPUT = "AOI_INPUT"
    AOI_OUTPUT = "AOI_OUTPUT"
    AOI_INOUT = "AOI_INOUT"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class TagReference:
    tag_name: str
    base_tag: str
    sub_element: Optional[str]      # e.g., "PRE", "ACC", "0", "Sts.Running", "[18]"
    scope_type: str                # "Controller" or "Program"
    program: Optional[str]         # None if Controller-scoped routine
    routine: str
    routine_type: str              # "RLL" or "ST"
    rung_number: Optional[int]     # 0-indexed rung number for RLL (None for ST)
    line_number: Optional[int]     # 1-indexed line number for ST (None for RLL)
    instruction_opcode: str        # e.g., "XIC", "OTE", "SCP", "AOI_MotorControl", "ST_ASSIGN"
    operand_index: int             # 0-based operand parameter index
    role: OperandRole
    raw_logic_snippet: str         # CDATA rung text or ST statement snippet
    alias_for: Optional[str] = None
    alias_target: Optional[str] = None

@dataclass
class TagReferenceReport:
    tag_name: str
    base_tag: str
    total_references: int
    read_count: int
    write_count: int
    control_count: int
    is_destructive: bool           # True if write_count > 0 or destructive AOI / control
    references: List[TagReference] = field(default_factory=list)
    programs_involved: List[str] = field(default_factory=list)
    routines_involved: List[str] = field(default_factory=list)
    coverage: Dict[str, Any] = field(default_factory=dict)
```

---

## Tasks & Execution Steps

### Task 1: Define Enums, Dataclasses, and Instruction Role Lookup Tables

**Files:**
- Modify: `src/l5x_analyzer/tag_cross_reference.py`
- Create: `tests/l5x_analyzer/test_deterministic_cross_reference.py`

- [ ] **Step 1: Write failing unit tests for `OperandRole` classification and dataclasses.**
  Test that `OperandRole` members serialize cleanly to JSON strings, and verify role resolution for bit, math, timer, counter, comparison, and scaling instructions.

  ```python
  # tests/l5x_analyzer/test_deterministic_cross_reference.py
  import pytest
  from l5x_analyzer.tag_cross_reference import (
      OperandRole,
      TagReference,
      TagReferenceReport,
      get_instruction_operand_role,
  )

  def test_operand_role_enum_values():
      assert OperandRole.READ_SOURCE.value == "READ_SOURCE"
      assert OperandRole.WRITE_DESTINATION.value == "WRITE_DESTINATION"
      assert OperandRole.READ_WRITE_CONTROL.value == "READ_WRITE_CONTROL"
      assert OperandRole.AOI_INPUT.value == "AOI_INPUT"
      assert OperandRole.AOI_OUTPUT.value == "AOI_OUTPUT"
      assert OperandRole.AOI_INOUT.value == "AOI_INOUT"

  def test_instruction_role_lookup_table():
      # Bit instructions
      assert get_instruction_operand_role("XIC", 0, 1) == OperandRole.READ_SOURCE
      assert get_instruction_operand_role("OTE", 0, 1) == OperandRole.WRITE_DESTINATION
      assert get_instruction_operand_role("ONS", 0, 1) == OperandRole.READ_WRITE_CONTROL

      # Math & Moves
      assert get_instruction_operand_role("MOV", 0, 2) == OperandRole.READ_SOURCE
      assert get_instruction_operand_role("MOV", 1, 2) == OperandRole.WRITE_DESTINATION
      assert get_instruction_operand_role("ADD", 0, 3) == OperandRole.READ_SOURCE
      assert get_instruction_operand_role("ADD", 2, 3) == OperandRole.WRITE_DESTINATION

      # Timers & Counters
      assert get_instruction_operand_role("TON", 0, 3) == OperandRole.READ_WRITE_CONTROL
      assert get_instruction_operand_role("TON", 1, 3) == OperandRole.READ_SOURCE
      assert get_instruction_operand_role("RES", 0, 1) == OperandRole.WRITE_DESTINATION

      # Scaling
      assert get_instruction_operand_role("SCP", 0, 6) == OperandRole.READ_SOURCE
      assert get_instruction_operand_role("SCP", 5, 6) == OperandRole.WRITE_DESTINATION
  ```

- [ ] **Step 2: Run pytest to verify the tests fail.**
  ```powershell
  python -m pytest tests/l5x_analyzer/test_deterministic_cross_reference.py -q
  ```
  *Expected:* Import or function resolution errors because `OperandRole` and `get_instruction_operand_role` are not yet exported.

- [ ] **Step 3: Implement `OperandRole`, `TagReference`, `TagReferenceReport`, and `INSTRUCTION_OPERAND_ROLES`.**
  Update `src/l5x_analyzer/tag_cross_reference.py` with the complete static dictionary covering Rockwell instructions:
  - Bit: `XIC`, `XIO`, `ONS`, `OSR`, `OSF`, `OTE`, `OTL`, `OTU`
  - Timers/Counters: `TON`, `TOF`, `RTO`, `CTU`, `CTD`, `RES`
  - Math/Move: `MOV`, `MVM`, `BTD`, `CPT`, `ADD`, `SUB`, `MUL`, `DIV`, `MOD`, `NEG`, `ABS`, `SQR`, `SQRT`, `TRUNC`, `FRD`, `TOD`, `SWPB`, `CLR`, `FLL`, `COP`, `CPS`, `GSV`, `SSV`
  - Comparisons: `EQU`, `NEQ`, `GRT`, `LES`, `GEQ`, `LEQ`, `LIM`, `MEQ`
  - Scaling: `SCP`, `SCPL`, `SCL`
  - Program Flow: `JSR`, `SBR`, `RET`, `FAL`, `FSC`, `SQI`, `SQO`, `SQL`

- [ ] **Step 4: Run the test suite and verify all role lookup tests pass.**
  ```powershell
  python -m pytest tests/l5x_analyzer/test_deterministic_cross_reference.py -q
  ```

---

### Task 2: Implement AST Logic Walkers with AOI, ST, Sub-Element, and ACD Support

**Files:**
- Modify: `src/l5x_analyzer/tag_cross_reference.py`
- Create: `tests/l5x_analyzer/fixtures/cross_ref_sample.L5X`
- Modify: `tests/l5x_analyzer/test_deterministic_cross_reference.py`

- [ ] **Step 1: Create synthetic fixture `cross_ref_sample.L5X`.**
  Include:
  - Controller tags: `Global_ESTOP`, `Htr1_Outlet_Temp`, `Htr1` (UDT instance), `N101` (Array).
  - Program `HeaterProg` with tags: `Pump_Cmd`, `Local_State`, `AOI_Instance_1`.
  - AOI Definition `AOI_MotorControl` with `EnableIn` (implicit), `StartCmd` (Input), `RunningOut` (Output), `DriveRef` (InOut).
  - RLL Routine with rungs executing `XIC(Global_ESTOP) OTE(Pump_Cmd);`, `MOV(Htr1.Outlet_Temp, N101[18]);`, `AOI_MotorControl(AOI_Instance_1, Pump_Cmd, Local_State, Htr1);`.
  - ST Routine with assignments: `Local_State := Htr1_Outlet_Temp > 180.0;`.

- [ ] **Step 2: Add failing unit tests for sub-element filtering, AOI mapping, ST statements, and ACD ingestion.**

  ```python
  # tests/l5x_analyzer/test_deterministic_cross_reference.py
  import os
  from l5x_analyzer.tag_cross_reference import find_tag_references, OperandRole

  FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "cross_ref_sample.L5X")

  def test_sub_element_matching_flag():
      # match_sub_elements=True should match Htr1 and Htr1.Outlet_Temp
      res_all = find_tag_references(FIXTURE_PATH, "Htr1", match_sub_elements=True)
      assert res_all["success"] is True
      assert res_all["summary"]["total"] >= 2

      # match_sub_elements=False should match ONLY base Htr1 without sub-elements
      res_exact = find_tag_references(FIXTURE_PATH, "Htr1", match_sub_elements=False)
      assert res_exact["success"] is True
      for ref in res_exact["references"]:
          assert ref["sub_element"] in (None, "")

  def test_aoi_parameter_role_resolution():
      res = find_tag_references(FIXTURE_PATH, "Pump_Cmd", program_scope="HeaterProg")
      assert res["success"] is True
      aoi_ref = next(r for r in res["references"] if r["instruction_opcode"] == "AOI_MotorControl")
      assert aoi_ref["role"] == OperandRole.AOI_INPUT.value

  def test_st_assignment_role_resolution():
      res = find_tag_references(FIXTURE_PATH, "Local_State", program_scope="HeaterProg")
      assert res["success"] is True
      st_write = next(r for r in res["references"] if r["routine_type"] == "ST")
      assert st_write["role"] == OperandRole.WRITE_DESTINATION.value
  ```

- [ ] **Step 3: Implement `find_tag_references` core enhancements in `src/l5x_analyzer/tag_cross_reference.py`.**
  - Add `match_sub_elements: bool = True` argument to `find_tag_references`.
  - Add `.ACD` file detection: if path ends with `.acd` (case-insensitive), invoke `convert_acd_to_l5x` in a temporary directory and parse the converted L5X.
  - In `_rll_rows`, map AOI parameter usages to `OperandRole.AOI_INPUT`, `OperandRole.AOI_OUTPUT`, and `OperandRole.AOI_INOUT`. Map operand 0 (instance) to `OperandRole.AOI_INOUT`.
  - In `_st_rows`, parse assignments (`:=`), comparison expressions, and function calls, attributing `WRITE_DESTINATION` to the left-hand target and `READ_SOURCE` to right-hand operands.
  - Populate `sub_element` in `TagReference` (e.g. `.Outlet_Temp`, `[18]`).
  - Calculate `is_destructive: bool = (write_count > 0 or control_count > 0)`.

- [ ] **Step 4: Run unit tests and verify they pass.**
  ```powershell
  python -m pytest tests/l5x_analyzer/test_deterministic_cross_reference.py -q
  ```

---

### Task 3: Legacy Wrapper Refactoring & MCP Server Registration

**Files:**
- Modify: `src/l5x_analyzer/l5x_mcp_integration.py`
- Modify: `src/l5x_analyzer/l5x_vector_db.py`
- Modify: `src/tag_analyzer/tag_mcp_integration.py`
- Modify: `src/mcp_server/studio5000_mcp_server.py`
- Modify: `tests/l5x_analyzer/test_tag_cross_reference.py`

- [ ] **Step 1: Write failing tests for MCP server tool registration and legacy wrapper delegation.**

  ```python
  # tests/l5x_analyzer/test_tag_cross_reference.py
  import asyncio, json
  from mcp_server.studio5000_mcp_server import Studio5000MCPServer, handle_mcp_request

  def test_find_tag_references_mcp_schema_and_call(tmp_path):
      server = Studio5000MCPServer(doc_root=".")
      listed = asyncio.run(handle_mcp_request(server, {
          "jsonrpc": "2.0", "id": 1, "method": "tools/list"
      }))
      tools = {t["name"]: t for t in listed["result"]["tools"]}
      assert "find_tag_references" in tools
      schema = tools["find_tag_references"]["inputSchema"]
      assert "match_sub_elements" in schema["properties"]
      assert schema["properties"]["match_sub_elements"]["type"] == "boolean"
  ```

- [ ] **Step 2: Update `src/l5x_analyzer/l5x_vector_db.py` and `l5x_mcp_integration.py`.**
  - Deprecate vector prompt querying in `find_related_components`.
  - Wire `find_related_components` to call `find_indexed_tag_references` and return deterministic results.
  - Update `L5XSDKMCPIntegration.find_tag_references` to accept `match_sub_elements: bool = True`.

- [ ] **Step 3: Update `src/mcp_server/studio5000_mcp_server.py`.**
  - Update `Studio5000MCPServer._register_tools()` for `find_tag_references` tool documentation.
  - Update `Studio5000MCPServer.find_tag_references` handler signature to include `match_sub_elements: bool = True`.
  - Update `tools/list` schema in `studio5000_mcp_server.py` with `match_sub_elements` property.

- [ ] **Step 4: Run MCP regression tests.**
  ```powershell
  python -m pytest tests/l5x_analyzer/test_tag_cross_reference.py tests/l5x_analyzer/test_deterministic_cross_reference.py -q
  ```

---

### Task 4: Real Fixture Verification (Kemco HA-105 & Thaw Room)

**Files:**
- Modify: `tests/l5x_analyzer/test_deterministic_cross_reference.py`

- [ ] **Step 1: Add integration test against optional real fixtures and the tracked synthetic fixture.**
  - Query `Htr1_Outlet_Temp` and assert exact where-used reference count (11 references across Scaling and Control routines).
  - Query `N101[18]` on Thaw Room and assert write occurrence from `ADD` instruction and read occurrence from downstream rungs.
  - Measure parse/index/query separately and record fixture, environment, cache state, and results; treat any performance target as a measured budget rather than a universal promise.

- [ ] **Step 2: Run full pytest suite across `tests/l5x_analyzer/` and `tests/acd/`.**
  ```powershell
  python -m pytest tests/l5x_analyzer/ tests/acd/ -q
  ```

- [ ] **Step 3: Run MCP Server Smoke Test.**
  ```powershell
  python src/mcp_server/studio5000_mcp_server.py --test
  ```
  *Expected:* Server initializes without warnings, registers `find_tag_references`, and completes sample queries successfully.

---

## MCP Schema Reference

```json
{
  "name": "find_tag_references",
  "description": "Deterministically finds all where-used logic references for a given tag across all routines in an L5X or ACD project, classifying each as read, write, control, or AOI parameter.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "file_path": {
        "type": "string",
        "description": "Path to the .L5X or .ACD project file."
      },
      "tag_name": {
        "type": "string",
        "description": "The exact tag name to search (e.g. 'Htr1_Outlet_Temp' or base tag 'Htr1')."
      },
      "program_scope": {
        "type": "string",
        "description": "Optional program name to filter program-scoped tags or specific routines."
      },
      "match_sub_elements": {
        "type": "boolean",
        "default": true,
        "description": "If true, searching for base tag 'Htr1' returns references to 'Htr1.Cmd', 'Htr1.Out', etc. Default is true."
      }
    },
    "required": ["file_path", "tag_name"]
  }
}
```

---

## Verification & Acceptance Checklist

- [ ] `find_tag_references` returns deterministic results with zero vector DB calls and reports unresolved/unsupported semantics explicitly.
- [ ] Every reference includes `program`, `routine`, `routine_type`, `rung_number` or `line_number`, `instruction_opcode`, `operand_index`, `role` (`OperandRole`), and `raw_logic_snippet`.
- [ ] AOI calls correctly map arguments against `AddOnInstructionDefinition` parameter usages (`Input` $\rightarrow$ `AOI_INPUT`, `Output` $\rightarrow$ `AOI_OUTPUT`, `InOut` $\rightarrow$ `AOI_INOUT`).
- [ ] Structured text assignments classify LHS as `WRITE_DESTINATION` and RHS as `READ_SOURCE`.
- [ ] Sub-element matching respects `match_sub_elements=True/False`.
- [ ] Synthetic unit tests meet the recorded budget; optional real-fixture and Studio validation results are reported separately.
- [ ] Server smoke test `python src/mcp_server/studio5000_mcp_server.py --test` runs cleanly.
