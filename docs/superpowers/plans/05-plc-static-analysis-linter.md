# PLC Static Analysis Linter & AST Syntax Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Backlog. The linter rules are not yet safe to describe as zero-false-positive or complete until scheduling scope, terminal semantics, and unresolved-instruction behavior are modeled.

**Goal:** Implement a conservative static analysis linter (`lint_plc_logic`) and AST syntax verifier for Rockwell Studio 5000 projects (.L5X and .ACD) and raw ladder logic strings, returning deterministic findings with explicit uncertainty.

**Architecture:** Build a dedicated verification subsystem in `src/verification/plc_linter.py` backed by deterministic AST traversal, routine call graph reachability analysis, and tag cross-referencing (`l5x_analyzer/tag_cross_reference.py`). Update `src/verification/sdk_verifier_clean.py` and `src/verification/sdk_verifier.py` with a complete Rockwell instruction taxonomy to fix BUG-09. Expose the static analysis engine via the `lint_plc_logic` MCP tool and update `validate_ladder_logic`.

**Tech Stack:** Python 3.12, XML ElementTree, dataclasses, regex/token parsing, standard library collections/graph utilities, pytest, MCP JSON-RPC protocol.

---

## Global Constraints

- **Conservative diagnostics:** Known valid instruction families must not trigger a false `INPUT_ONLY` finding, but the plan must not claim zero false positives for unknown AOIs or incomplete project metadata. Emit `UNKNOWN_SEMANTICS`/`POSSIBLE_*` diagnostics when certainty is unavailable.
- **Deterministic & Offline:** Analysis must run completely offline without relying on Rockwell SDK runtime, network connections, or vector databases.
- **Severity Classification:**
  - `ERROR`: Structural syntax defects (unbalanced brackets `[...]`, empty branches, missing outputs on rungs with inputs).
  - `WARNING`: Dangerous semantic anti-patterns (duplicate destructive `OTE` coils in same scan cycle, unpaired `OTL` without `OTU`, unreachable routines uncalled by `JSR`).
  - `INFO`: Code quality / hygiene diagnostics (unused tag definitions with 0 AST references).
- **Graceful File Ingestion:** Support both exported `.L5X` files and `.ACD` files (via transparent offline conversion in `l5x_analyzer.acd_offline_convert`).

## Review gates before implementation

- Reuse the shared instruction-role/output table from Plan-01 and the comment graph. A valid opcode is not automatically a terminal output: classify terminal behavior by instruction semantics and AOI metadata.
- Duplicate `OTE` is only a warning when writes occur in the same scheduling domain (task/program/routine execution context). Across independently scheduled tasks, report `POSSIBLE_DUPLICATE_OTE` unless task metadata proves a common scan.
- `OTL`/`OTU` pairing is advisory: account for aliases, member/bit identity, reset paths, and writes by other instructions before calling a latch unpaired.
- Reachability roots must include task-owned main routines, event/fault routines, and configured entry points. “No incoming JSR edge” is not sufficient evidence of dead code.
- Syntax checks must tokenize strings/literals and nested calls; raw bracket counts are a quick diagnostic, not a complete RLL parser. Never claim 100% precision without a known-instruction/fixture coverage report.
- **Preserve Existing Worktree:** Preserve `tests/test_direct_acd_deliverables.py`; do not stage or overwrite unrelated changes.
- **Engineering Review Requirement:** Generated linter reports must emphasize that static analysis diagnostics are advisory for design review prior to live controller commissioning.

---

## File Map

### Create:
- `src/verification/plc_linter.py` — Core static analysis engine, rule registry, AST branch validator, JSR call graph analyzer, and report formatter.
- `tests/verification/test_plc_linter.py` — Unit and integration tests covering all 6 static analysis rules, rule filtering, multi-program scope, and error/warning reporting.
- `tests/verification/test_sdk_verifier_bug09.py` — Regression test suite confirming BUG-09 resolution across all standard Studio 5000 instruction categories.
- `tests/verification/fixtures/linter_sample_project.L5X` — Synthetic L5X project fixture containing clean logic, duplicate OTEs, unpaired latches, dead routines, and unused tags.

### Modify:
- `src/verification/sdk_verifier_clean.py` — Update `_validate_basic_structure` and `_validate_ladder_syntax` to fix BUG-09 and validate branch brackets.
- `src/verification/sdk_verifier.py` — Mirror fixes from clean verifier to maintain parity.
- `src/verification/__init__.py` — Export `PLCLinter`, `LintFinding`, `LintSeverity`, `LintReport`, and `LintRuleId`.
- `src/mcp_server/studio5000_mcp_server.py` — Register `lint_plc_logic` MCP tool, add handler method, and update `tools/list` schema.

### Do Not Modify:
- `tests/test_direct_acd_deliverables.py` (contains unrelated user worktree modifications).
- Core parser binaries or Kaitai structs in `src/acd/`.

---

## Data Models & Type Specifications

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class LintSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class LintRuleId(str, Enum):
    BRANCH_SYNTAX = "RULE_01_BRANCH_SYNTAX"
    VALID_OUTPUT = "RULE_02_VALID_OUTPUT"
    DUPLICATE_OTE = "RULE_03_DUPLICATE_OTE"
    UNPAIRED_LATCH = "RULE_04_UNPAIRED_LATCH"
    UNREACHABLE_ROUTINE = "RULE_05_UNREACHABLE_ROUTINE"
    UNUSED_TAG = "RULE_06_UNUSED_TAG"


@dataclass(frozen=True)
class LintFinding:
    rule_id: str
    rule_name: str
    severity: LintSeverity
    message: str
    program: Optional[str] = None
    routine: Optional[str] = None
    rung_number: Optional[int] = None
    line_number: Optional[int] = None
    tag_name: Optional[str] = None
    snippet: Optional[str] = None


@dataclass
class LintReport:
    success: bool
    total_errors: int
    total_warnings: int
    total_info: int
    findings: List[LintFinding] = field(default_factory=list)
    rules_evaluated: List[str] = field(default_factory=list)
    programs_analyzed: List[str] = field(default_factory=list)
    routines_analyzed: int = 0
    rungs_analyzed: int = 0
    tags_analyzed: int = 0
    summary: Dict[str, Any] = field(default_factory=dict)
```

---

## Tasks & Execution Steps

### Task 1: Implement Data Models, Rule Definitions, and Branch Syntax Validator (Rule 1)

**Files:**
- Create: `src/verification/plc_linter.py`
- Create: `tests/verification/test_plc_linter.py`

**Interfaces:**
```python
def validate_branch_syntax(rung_text: str, rung_number: Optional[int] = None) -> List[LintFinding]:
    """Validates bracket balance, branch commas, and rejects empty or trailing branch legs."""
    ...
```

- [ ] **Step 1: Write failing unit tests for Rule 1 (Branch Syntax & Bracket Validator).**
  Cover unbalanced brackets `[XIC(A) XIC(B)`, mismatched closing `XIC(A)]`, empty branches `[,]`, leading branch separators `[, XIC(A)]`, trailing branch separators `[XIC(A) ,]`, empty brackets `[]`, nested brackets `[[XIC(A), XIC(B)] XIC(C), XIC(D)]`, and commas outside brackets.

  ```python
  # tests/verification/test_plc_linter.py
  import pytest
  from verification.plc_linter import LintSeverity, LintRuleId, validate_branch_syntax

  def test_branch_syntax_valid_single_and_nested():
      valid_rungs = [
          "XIC(Start) OTE(Run);",
          "[XIC(Start) , XIC(Run)] XIO(Stop) OTE(Run);",
          "[[XIC(A) , XIC(B)] XIC(C) , XIC(D)] OTE(Out);",
      ]
      for rung in valid_rungs:
          findings = validate_branch_syntax(rung)
          assert len(findings) == 0, f"Expected clean syntax for: {rung}, got {findings}"

  def test_branch_syntax_unbalanced_brackets():
      findings = validate_branch_syntax("[XIC(A) XIC(B) OTE(C);")
      assert len(findings) == 1
      assert findings[0].severity == LintSeverity.ERROR
      assert findings[0].rule_id == LintRuleId.BRANCH_SYNTAX.value
      assert "Unbalanced" in findings[0].message

  def test_branch_syntax_empty_and_trailing_branches():
      invalid_rungs = [
          "[XIC(A), ] OTE(B);",
          "[, XIC(A)] OTE(B);",
          "[,] OTE(B);",
          "[] OTE(B);",
      ]
      for rung in invalid_rungs:
          findings = validate_branch_syntax(rung)
          assert len(findings) >= 1
          assert any(f.severity == LintSeverity.ERROR for f in findings)
  ```

- [ ] **Step 2: Run pytest and verify tests fail for the missing module.**
  ```bash
  python -m pytest tests/verification/test_plc_linter.py -q
  ```
  Expected result: ModuleNotFoundError (`verification.plc_linter` does not exist).

- [ ] **Step 3: Implement `src/verification/plc_linter.py` with enums, dataclasses, and `validate_branch_syntax`.**
  Implement a stack-based bracket/delimiter tokenizer that tracks nesting depth, ensures commas only appear within `[...]` structures (excluding commas inside `INSTR(...)` operand parentheses), and validates that each limb between commas contains at least one non-whitespace character.

- [ ] **Step 4: Run pytest to verify Rule 1 tests pass.**
  ```bash
  python -m pytest tests/verification/test_plc_linter.py -q
  ```
  Expected result: All branch syntax tests pass.

- [ ] **Step 5: Commit changes for Task 1.**
  ```bash
  git add src/verification/plc_linter.py tests/verification/test_plc_linter.py
  git commit -m "Linter: implement Rule 1 branch syntax and bracket validator"
  ```

---

### Task 2: Implement Output Instruction Taxonomies & Fix BUG-09 in SDK Verifiers (Rule 2)

**Files:**
- Modify: `src/verification/plc_linter.py`
- Modify: `src/verification/sdk_verifier_clean.py:230-316`
- Modify: `src/verification/sdk_verifier.py:230-316`
- Create: `tests/verification/test_sdk_verifier_bug09.py`

**Taxonomy Reference:**
```python
VALID_OUTPUT_INSTRUCTIONS: Set[str] = {
    # Coils & One-shots
    "OTE", "OTL", "OTU", "ONS", "OSR", "OSF",
    # Timers & Counters
    "TON", "TOF", "RTO", "CTU", "CTD", "RES", "TONR", "TOFR", "UPDN",
    # Math & Conversion
    "ADD", "SUB", "MUL", "DIV", "MOD", "CPT", "CLR", "NEG", "ABS",
    "SQR", "SQRT", "TOD", "FRD", "DEG", "RAD", "TRN",
    # Data Move & Arrays
    "MOV", "MVM", "COP", "CPS", "FLL", "AVE", "SRT", "STD", "SWPB",
    "BTD", "BSL", "BSR", "FFL", "FFU", "LFL", "LFU", "FAL",
    # Program Flow & Control
    "JSR", "RET", "SBR", "TND", "JMP", "LBL", "MCR", "FOR", "BRK", "UID", "UIE", "NOP",
    # System & Communications
    "GSV", "SSV", "MSG", "PID", "PIDE", "ALMA", "ALMD", "IOT",
    # Motion Control
    "MSO", "MSF", "MAJ", "MAM", "MAS", "MAH", "MAG", "MAPC", "MATC",
    "MAXC", "MDAC", "MDCC", "MDOC", "MDSF", "MAFR", "MRAT", "MRST",
}

INPUT_CONDITIONAL_INSTRUCTIONS: Set[str] = {
    "XIC", "XIO", "EQU", "NEQ", "LES", "LEQ", "GRT", "GEQ", "LIM", "MEQ", "CMP", "AFI",
}
```

- [ ] **Step 1: Write failing regression tests for BUG-09 and Rule 2.**
  Verify that timer rungs, math rungs, counter rungs, move rungs, subroutine calls, and AOI calls produce zero errors or `INPUT_ONLY` warnings in both `SDKVerifier` and `PLCLinter`.

  ```python
  # tests/verification/test_sdk_verifier_bug09.py
  import pytest
  from verification.sdk_verifier_clean import SDKVerifier
  from verification.plc_linter import validate_rung_output_instruction, LintSeverity

  @pytest.mark.asyncio
  async def test_sdk_verifier_no_false_positive_input_only():
      verifier = SDKVerifier()
      test_rungs = [
          "XIC(Run_Cmd) TON(Timer1, 5000, 0);",
          "XIC(Trigger) CTU(Counter1, 100, 0);",
          "XIC(Calculate) ADD(ValA, ValB, Result);",
          "XIC(Enable) MOV(SourceVal, DestVal);",
          "XIC(Start) JSR(SubRoutine_01, 0);",
          "XIC(Alarm_Trigger) ALMA(AlarmTag);",
          "XIC(In1) COP(SourceArray[0], DestArray[0], 10);",
      ]
      for rung in test_rungs:
          result = await verifier.verify_ladder_logic(rung)
          assert result.success is True
          input_only_warnings = [w for w in result.warnings if w.code == "INPUT_ONLY"]
          assert len(input_only_warnings) == 0, f"BUG-09 reproduced on valid rung: {rung}"

  def test_linter_rule_2_missing_output_detection():
      # Rung with only inputs and no output instruction must fail Rule 2
      bad_rung = "XIC(Sensor_1) XIO(Sensor_2) EQU(Val1, Val2);"
      findings = validate_rung_output_instruction(bad_rung)
      assert len(findings) == 1
      assert findings[0].severity == LintSeverity.ERROR
      assert "missing output instruction" in findings[0].message.lower()
  ```

- [ ] **Step 2: Run pytest and confirm failure due to BUG-09.**
  ```bash
  python -m pytest tests/verification/test_sdk_verifier_bug09.py -q
  ```
  Expected result: Failures due to `INPUT_ONLY` warning being generated on `TON`, `ADD`, `MOV`, etc.

- [ ] **Step 3: Update `sdk_verifier_clean.py` and `sdk_verifier.py`.**
  - In `_validate_basic_structure(rung, rung_number)`: Extract all instruction opcodes in the rung. If the rung contains conditional input instructions (`INPUT_CONDITIONAL_INSTRUCTIONS`) and zero output instructions from `VALID_OUTPUT_INSTRUCTIONS` (and no unknown instruction calls that could be AOIs), flag `INPUT_ONLY`.
  - In `_validate_ladder_syntax(rung, rung_number)`: Add bracket balance validation (`rung.count('[') == rung.count(']')`).
  - Implement `validate_rung_output_instruction` in `src/verification/plc_linter.py`.

- [ ] **Step 4: Run pytest and verify all BUG-09 tests pass.**
  ```bash
  python -m pytest tests/verification/test_sdk_verifier_bug09.py -q
  ```
  Expected result: All tests pass with 0 `INPUT_ONLY` false positives.

- [ ] **Step 5: Commit changes for Task 2.**
  ```bash
  git add src/verification/plc_linter.py src/verification/sdk_verifier_clean.py src/verification/sdk_verifier.py tests/verification/test_sdk_verifier_bug09.py
  git commit -m "Verification: fix BUG-09 false-positive INPUT_ONLY and implement Rule 2"
  ```

---

### Task 3: Implement Duplicate Destructive Coil & Unpaired Latch/Unlatch Detectors (Rules 3 & 4)

**Files:**
- Modify: `src/verification/plc_linter.py`
- Modify: `tests/verification/test_plc_linter.py`

**Interfaces:**
```python
def check_duplicate_destructive_coils(
    rungs_by_routine: Dict[Tuple[str, str], List[Tuple[int, str]]]
) -> List[LintFinding]:
    """Detects multiple OTE instructions writing to the same BOOL tag within the same program/controller scope."""
    ...

def check_unpaired_latches(
    rungs_by_routine: Dict[Tuple[str, str], List[Tuple[int, str]]]
) -> List[LintFinding]:
    """Detects OTL instructions without matching OTU (and vice versa) for the same tag."""
    ...
```

- [ ] **Step 1: Write failing unit tests for Rule 3 (Duplicate OTE) and Rule 4 (Unpaired Latches).**
  - Test detecting duplicate `OTE(Motor_Run)` across Rung 0 and Rung 5 in routine `MotorRoutine`.
  - Test verifying `OTE` to different bits of a word (`ControlWord.0` vs `ControlWord.1`) does not false-positive as duplicate coil.
  - Test detecting `OTL(Temp_Alarm)` with no `OTU` in project (Severity: `WARNING`).
  - Test detecting `OTU(Clear_Bit)` with no `OTL` in project.
  - Test clean latch/unlatch pairs generate zero warnings.

  ```python
  # tests/verification/test_plc_linter.py additions
  def test_duplicate_ote_detection():
      rungs = {
          ("MainProgram", "MotorRoutine"): [
              (0, "XIC(Auto_Mode) XIC(Start_PB) OTE(Motor_Run);"),
              (5, "XIC(Manual_Mode) XIC(Jog_PB) OTE(Motor_Run);"),  # Double OTE!
              (10, "XIC(Light_Sw) OTE(Light_Out);"),
          ]
      }
      findings = check_duplicate_destructive_coils(rungs)
      assert len(findings) == 1
      assert findings[0].severity == LintSeverity.WARNING
      assert findings[0].rule_id == LintRuleId.DUPLICATE_OTE.value
      assert "Motor_Run" in findings[0].message
      assert findings[0].tag_name == "Motor_Run"

  def test_unpaired_latch_detection():
      rungs = {
          ("MainProgram", "AlarmRoutine"): [
              (0, "XIC(High_Temp) OTL(Temp_Alarm);"),  # Missing OTU
              (1, "XIC(High_Press) OTL(Press_Alarm);"),
              (2, "XIC(Reset_PB) OTU(Press_Alarm);"),   # Paired
          ]
      }
      findings = check_unpaired_latches(rungs)
      assert len(findings) == 1
      assert findings[0].severity == LintSeverity.WARNING
      assert findings[0].rule_id == LintRuleId.UNPAIRED_LATCH.value
      assert "Temp_Alarm" in findings[0].message
  ```

- [ ] **Step 2: Run pytest to confirm tests fail before implementation.**
  ```bash
  python -m pytest tests/verification/test_plc_linter.py -k "duplicate_ote or unpaired_latch" -q
  ```
  Expected result: NameError/ImportError for functions not yet defined.

- [ ] **Step 3: Implement `check_duplicate_destructive_coils` and `check_unpaired_latches` in `plc_linter.py`.**
  - Use `l5x_analyzer.rll_parser.find_calls` to extract instruction calls and target operands deterministically.
  - Normalize tag identifiers and bit references.
  - Group write occurrences by tag and program scope.
  - Emit structured `LintFinding` objects with program, routine, and rung numbers.

- [ ] **Step 4: Run pytest to verify Rule 3 & 4 tests pass.**
  ```bash
  python -m pytest tests/verification/test_plc_linter.py -k "duplicate_ote or unpaired_latch" -q
  ```
  Expected result: All tests pass.

- [ ] **Step 5: Commit changes for Task 3.**
  ```bash
  git add src/verification/plc_linter.py tests/verification/test_plc_linter.py
  git commit -m "Linter: implement Rule 3 duplicate OTE and Rule 4 unpaired latch checkers"
  ```

---

### Task 4: Implement Unreachable Routine Call Graph Walker & Unused Tag Detector (Rules 5 & 6)

**Files:**
- Modify: `src/verification/plc_linter.py`
- Modify: `tests/verification/test_plc_linter.py`

**Interfaces:**
```python
def check_unreachable_routines(
    programs: Dict[str, Dict[str, Any]],
    routine_rungs: Dict[Tuple[str, str], List[Tuple[int, str]]],
) -> List[LintFinding]:
    """Constructs a directed JSR call graph per program starting at MainRoutineName; flags uncalled routines."""
    ...

def check_unused_tags(
    declared_tags: Dict[str, List[Dict[str, str]]],
    referenced_tags: Set[str],
) -> List[LintFinding]:
    """Identifies declared tags with 0 AST references, excluding I/O module mapped and produced/consumed tags."""
    ...
```

- [ ] **Step 1: Write failing unit tests for Rule 5 (Unreachable Routine) and Rule 6 (Unused Tag).**
  - Test Program with `MainRoutine="MainRoutine"`, where `MainRoutine` calls `ConveyorLogic`, and `DeadRoutine` is never called. Assert `DeadRoutine` flagged with `WARNING`.
  - Test that `FaultRoutineName` is recognized as an entry point and not flagged as dead logic.
  - Test tag declared in `<Tags>` with 0 logic references is flagged with `INFO`.
  - Test I/O mapped tags (`Local:1:I`) and Produced/Consumed tags are not flagged as unused.

  ```python
  # tests/verification/test_plc_linter.py additions
  def test_unreachable_routine_detection():
      programs = {
          "MainProgram": {
              "main_routine": "MainRoutine",
              "fault_routine": None,
              "routines": ["MainRoutine", "ConveyorLogic", "DeadRoutine"],
          }
      }
      routine_rungs = {
          ("MainProgram", "MainRoutine"): [
              (0, "XIC(Always_True) JSR(ConveyorLogic, 0);"),
          ],
          ("MainProgram", "ConveyorLogic"): [
              (0, "XIC(Run) OTE(Conveyor_Motor);"),
          ],
          ("MainProgram", "DeadRoutine"): [
              (0, "XIC(Start) OTE(Dead_Output);"),
          ],
      }
      findings = check_unreachable_routines(programs, routine_rungs)
      assert len(findings) == 1
      assert findings[0].severity == LintSeverity.WARNING
      assert findings[0].rule_id == LintRuleId.UNREACHABLE_ROUTINE.value
      assert "DeadRoutine" in findings[0].message
      assert findings[0].routine == "DeadRoutine"

  def test_unused_tag_detection():
      declared = {
          "Controller": [
              {"name": "UsedTag", "data_type": "DINT", "tag_type": "Base"},
              {"name": "OrphanTag", "data_type": "REAL", "tag_type": "Base"},
              {"name": "Local:1:I", "data_type": "AB:1756_DI:I:0", "tag_type": "Base"}, # I/O
          ]
      }
      referenced = {"UsedTag"}
      findings = check_unused_tags(declared, referenced)
      assert len(findings) == 1
      assert findings[0].severity == LintSeverity.INFO
      assert findings[0].rule_id == LintRuleId.UNUSED_TAG.value
      assert findings[0].tag_name == "OrphanTag"
  ```

- [ ] **Step 2: Run pytest to confirm tests fail before implementation.**
  ```bash
  python -m pytest tests/verification/test_plc_linter.py -k "unreachable_routine or unused_tag" -q
  ```

- [ ] **Step 3: Implement `check_unreachable_routines` and `check_unused_tags` in `plc_linter.py`.**
  - For Rule 5: Extract `JSR` call targets from rung logic using regex/RLL parser. Construct directed adjacency list `graph[caller] = [callees]`. Perform BFS/DFS from `MainRoutineName` and `FaultRoutineName`.
  - For Rule 6: Filter out special tags (I/O colon addresses, produce/consume properties). Cross-reference declared symbols against the referenced token set.

- [ ] **Step 4: Run pytest to verify Rule 5 & 6 tests pass.**
  ```bash
  python -m pytest tests/verification/test_plc_linter.py -k "unreachable_routine or unused_tag" -q
  ```
  Expected result: All tests pass.

- [ ] **Step 5: Commit changes for Task 4.**
  ```bash
  git add src/verification/plc_linter.py tests/verification/test_plc_linter.py
  git commit -m "Linter: implement Rule 5 unreachable routine and Rule 6 unused tag detectors"
  ```

---

### Task 5: Implement `PLCLinter` Orchestrator, L5X/ACD Project Parser, and Report Engine

**Files:**
- Modify: `src/verification/plc_linter.py`
- Modify: `src/verification/__init__.py`
- Create: `tests/verification/fixtures/linter_sample_project.L5X`
- Modify: `tests/verification/test_plc_linter.py`

**Interfaces:**
```python
class PLCLinter:
    """Orchestrates static analysis across L5X/ACD projects and raw ladder text."""

    def __init__(self, rules: Optional[List[str]] = None):
        self.enabled_rules = set(rules) if rules else set(r.value for r in LintRuleId)

    def lint_project(self, file_path: str, program_scope: Optional[str] = None) -> LintReport:
        """Parses L5X or converted ACD file, runs all enabled lint rules, and returns a structured LintReport."""
        ...

    def lint_ladder_text(self, ladder_text: str) -> LintReport:
        """Runs syntax and rung-level rules (Rule 1 & 2) on a raw ladder string."""
        ...
```

- [ ] **Step 1: Create synthetic L5X fixture (`tests/verification/fixtures/linter_sample_project.L5X`).**
  Create an XML fixture containing:
  - 2 Programs (`MainProgram` with `MainRoutine`, `SubRoutine`, `DeadRoutine`, and `SafetyProgram`).
  - Rungs with valid `TON`, `ADD`, `MOV`.
  - Rung with malformed bracket `[XIC(A) XIC(B)`.
  - Rung with duplicate `OTE(Pump_Run)`.
  - Rung with `OTL(Unpaired_Bit)` without `OTU`.
  - Unused tag `Spare_Analog_In`.

- [ ] **Step 2: Write failing end-to-end integration tests for `PLCLinter.lint_project` and `PLCLinter.lint_ladder_text`.**
  Assert that linting the fixture reports the exact expected counts for errors, warnings, and info items, and that rule filtering (`rules=["RULE_01_BRANCH_SYNTAX"]`) restricts evaluation to only specified rules.

- [ ] **Step 3: Implement `PLCLinter` in `src/verification/plc_linter.py`.**
  - Integrate XML ElementTree parsing with support for `.ACD` via `l5x_analyzer.acd_offline_convert.convert_acd_to_l5x`.
  - Extract controller tags, program tags, routines, rungs, and CDATA logic.
  - Coordinate the execution of all 6 rules according to `self.enabled_rules`.
  - Assemble comprehensive `LintReport` with summary metrics.
  - Update `src/verification/__init__.py` with all exports.

- [ ] **Step 4: Run pytest on the full verification test suite.**
  ```bash
  python -m pytest tests/verification/ -q
  ```
  Expected result: All unit and integration tests pass.

- [ ] **Step 5: Commit changes for Task 5.**
  ```bash
  git add src/verification/plc_linter.py src/verification/__init__.py tests/verification/
  git commit -m "Linter: implement PLCLinter orchestrator and project parser"
  ```

---

### Task 6: Wire MCP Tool `lint_plc_logic` and Run Verification Smoke Tests

**Files:**
- Modify: `src/mcp_server/studio5000_mcp_server.py`
- Modify: `tests/test_mcp_workaround_fixes.py`

**MCP Tool Definition:**
```json
{
  "name": "lint_plc_logic",
  "description": "Performs comprehensive static analysis linting on an L5X or ACD project, detecting branch syntax errors, duplicate destructive OTE coils, unlatched OTLs, uncalled dead routines, and unused tags.",
  "parameters": {
    "type": "object",
    "properties": {
      "file_path": {
        "type": "string",
        "description": "Path to the .L5X or .ACD project file."
      },
      "rules": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Optional list of specific rule IDs to run (e.g. ['RULE_01_BRANCH_SYNTAX', 'RULE_03_DUPLICATE_OTE']). Runs all rules by default."
      },
      "program_scope": {
        "type": "string",
        "description": "Optional program name to restrict analysis scope."
      }
    },
    "required": ["file_path"]
  }
}
```

- [ ] **Step 1: Add failing MCP tool dispatch test in `tests/test_mcp_workaround_fixes.py`.**
  Test calling `lint_plc_logic` over `handle_mcp_request` and verify structured response format.

- [ ] **Step 2: Register `lint_plc_logic` in `Studio5000MCPServer._register_tools()`.**
  - Add tool registration call in `_register_tools()`.
  - Add `async def lint_plc_logic(self, file_path: str, rules: Optional[List[str]] = None, program_scope: Optional[str] = None) -> Dict[str, Any]:` handler.
  - Add schema definition to `tools/list` dispatcher.

- [ ] **Step 3: Run pytest and the server smoke test.**
  ```bash
  python -m pytest tests/test_mcp_workaround_fixes.py tests/verification/ -q
  python src/mcp_server/studio5000_mcp_server.py --test
  ```
  Expected result: All tests pass and `--test` completes successfully.

- [ ] **Step 4: Commit changes for Task 6.**
  ```bash
  git add src/mcp_server/studio5000_mcp_server.py tests/test_mcp_workaround_fixes.py
  git commit -m "Linter: expose lint_plc_logic MCP tool and register schema"
  ```
