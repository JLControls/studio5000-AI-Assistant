# Core Reliability Bug Fixes & MCP Protocol Framing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Partial implementation. Project-overview protection and several framing/export fixes already exist; this plan is a verification delta, not a claim that all six defects remain open.

**Goal:** Verify the remaining core reliability and framing contracts across `l5x_analyzer`, `code_generator`, `ai_assistant`, and `mcp_server`, including clean stdio JSON-RPC communication, correct program context, deterministic project errors, safe 3-wire logic, valid opcode mappings, and Python 3.12 entry-point enforcement.

**Architecture:** Fix individual isolated reliability bugs in their respective subsystems with focused regression tests. Eliminate unformatted `stdout` pollution across code generator modules to protect JSON-RPC framing over stdio. Parameterize routine L5X export wrappers with configurable target `Program` context. Update motor logic generation templates with industry-standard seal-in branches. Purge fictitious `PRODUCE`/`CONSUME` ladder opcodes. Add Python 3.12 version guard at MCP server entry.

**Tech Stack:** Python 3.12, XML ElementTree, stdio JSON-RPC 2.0, pytest.

---

## Global Constraints

- **Preserve JSON-RPC Framing:** Standard output (`sys.stdout`) must be reserved EXCLUSIVELY for JSON-RPC response payloads when running as an MCP server. All diagnostics, errors, progress indicators, and helper dumps must write to `sys.stderr` or standard logging.
- **Backward Compatibility:** All modified function signatures must retain backward compatibility with existing callers using default parameter values or alias fallbacks (`program_name` / `target_program`).
- **Deterministic Failure:** If a requested project stem is not found in `indexed_projects`, `get_project_overview` must fail with an informative error listing available projects; it must NEVER fall back to another project's metadata.
- **PLC Safety Standards:** Industrial motor start/stop circuits must include a seal-in latch branch (`[XIC(Start) , XIC(Motor)]`) to prevent dangerous unlatched jog-only behavior.
- **Preserve Existing Worktree:** Preserve `tests/test_direct_acd_deliverables.py`; do not stage or overwrite unrelated changes.

## Review gates before implementation

- `get_project_overview` must list available indexed project names on mismatch; a wrong-project rejection test is required even when the current implementation already rejects the fallback.
- Test stdout framing through the actual MCP subprocess. Intentional `--test` diagnostics are a separate mode and must not be used as evidence that runtime JSON-RPC stdout is clean.
- Keep one canonical effective target-program parameter (`target_program` with a backward-compatible alias) and test both generated XML context and MCP schema.
- `PRODUCE`/`CONSUME` are connection properties, not generic executable ladder instructions. Do not map them to `MSG` without valid MSG control operands; prefer removing the mapping or modeling the connection metadata separately.
- Apply the Python 3.12 guard in the executable entry point (`main()` or a subprocess wrapper), not at module import, so library imports and test collection remain usable.

---

## File Map

### Create:
- `tests/test_core_bugfixes.py` — Comprehensive regression test suite verifying all 6 bug fixes (overview rejection, stdout framing integrity, target program routine export, 3-wire motor latch, communication opcode validity, and Python version check).

### Modify:
- `src/l5x_analyzer/l5x_mcp_integration.py` — BUG-04: Ensure `get_project_overview` never returns another project's overview and returns available indexed project names on mismatch.
- `src/code_generator/l5x_generator.py` — BUG-06 & BUG-07: Redirect all `print()` statements to `sys.stderr`, support `target_program` parameter in `generate_routine_export` and `save_routine_export`, and update motor example.
- `src/ai_assistant/code_assistant.py` — BUG-06 & BUG-08: Update `_generate_start_stop_logic` to emit seal-in latch branch `[XIC(start) , XIC(motor) ]`, redirect `print()` to `sys.stderr`.
- `src/ai_assistant/enhanced_code_assistant.py` — Action 13: Replace `'produce': 'PRODUCE'` and `'consume': 'CONSUME'` with `'MSG'`.
- `src/ai_assistant/enhanced_ladder_generator.py` — BUG-09 / Action 13: Replace fictitious `'PRODUCE'` and `'CONSUME'` opcodes in `comm_mappings` with `'MSG'`.
- `src/ai_assistant/enhanced_main_assistant.py` — BUG-06: Redirect all diagnostic `print()` statements in example runners to `sys.stderr`.
- `src/drawings_analyzer/pdf_parser.py` — BUG-06: Redirect test `print()` calls in standalone runner to `sys.stderr`.
- `src/documentation/instruction_vector_db.py` — BUG-06: Redirect test `print()` calls in standalone runner to `sys.stderr`.
- `src/mcp_server/studio5000_mcp_server.py` — Action 19 & BUG-07: Add Python 3.12 startup runtime guard, update `create_l5x_routine` handler and `tools/list` schema to support `target_program`.

### Do Not Modify:
- `tests/test_direct_acd_deliverables.py` (pre-existing worktree modification).

---

## Tasks & Execution Steps

### Task 1: Fix BUG-04 (Reject Unindexed Projects in `get_project_overview`)

**Files:**
- Modify: `src/l5x_analyzer/l5x_mcp_integration.py:710-735`
- Create: `tests/test_core_bugfixes.py`

**Defect & Fix:**
When `project_name` is not in `indexed_projects`, never return another project's overview. Return a structured error listing available indexed projects.

- [ ] **Step 1: Write failing regression test in `tests/test_core_bugfixes.py`.**
  ```python
  # tests/test_core_bugfixes.py
  import asyncio
  import pytest
  from l5x_analyzer.l5x_vector_db import L5XVectorDatabase
  from l5x_analyzer.l5x_mcp_integration import L5XSDKMCPIntegration

  @pytest.mark.asyncio
  async def test_bug04_get_project_overview_rejects_missing_project(tmp_path):
      vdb = L5XVectorDatabase(cache_dir=str(tmp_path / "cache"))
      vdb.indexed_projects["Kemco_HA105"] = {
          "file_count": 1,
          "chunk_count": 20,
          "structure": {
              "controller": "Kemco_Ctl",
              "programs": ["MainProgram"],
              "routines": [],
              "udts": [],
          },
      }
      integration = L5XSDKMCPIntegration(vector_db=vdb)

      result = await integration.get_project_overview("UnindexedProject.L5X")
      assert result["success"] is False
      assert "UnindexedProject" in result["error"]
      assert "Kemco_HA105" in result["error"]
      assert "Kemco_Ctl" not in result.get("controller", "")
  ```

- [ ] **Step 2: Run pytest to verify the test runs.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_bug04" -q
  ```

- [ ] **Step 3: Update `src/l5x_analyzer/l5x_mcp_integration.py`.**
  In `get_project_overview`:
  ```python
  if project_name not in indexed_projects:
      available = list(indexed_projects.keys())
      if not available:
          return {
              'success': False,
              'error': (
                  f"Project '{project_name}' is not indexed. No L5X data is "
                  "available; run index_exported_l5x_files or index_acd_project first."
              )
          }
      return {
          'success': False,
          'error': (
              f"Project '{project_name}' is not indexed. Available indexed projects: {available}. "
              f"Run index_exported_l5x_files or index_acd_project for this project first."
          )
      }
  ```

- [ ] **Step 4: Run pytest to verify BUG-04 test passes.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_bug04" -q
  ```
  Expected result: Test passes.

- [ ] **Step 5: Commit changes for Task 1.**
  ```bash
  git add src/l5x_analyzer/l5x_mcp_integration.py tests/test_core_bugfixes.py
  git commit -m "L5X Analyzer: fix BUG-04 get_project_overview unindexed project error"
  ```

---

### Task 2: Fix BUG-06 (Redirect stdout `print()` to stderr to Protect JSON-RPC Protocol)

**Files:**
- Modify: `src/code_generator/l5x_generator.py:327, 398, 474-479`
- Modify: `src/ai_assistant/code_assistant.py:559-563`
- Modify: `src/ai_assistant/enhanced_main_assistant.py:643-653`
- Modify: `src/drawings_analyzer/pdf_parser.py:881-898`
- Modify: `src/documentation/instruction_vector_db.py:374-397`
- Modify: `tests/test_core_bugfixes.py`

- [ ] **Step 1: Write failing regression test for stdout isolation.**
  Capture `sys.stdout` and invoke generator / assistant helper functions; assert that `sys.stdout` receives zero unformatted strings.

  ```python
  # tests/test_core_bugfixes.py additions
  import sys
  import io
  from code_generator.l5x_generator import L5XGenerator, Routine, LadderRung

  def test_bug06_l5x_generator_error_does_not_pollute_stdout(monkeypatch, tmp_path):
      captured_stdout = io.StringIO()
      captured_stderr = io.StringIO()
      monkeypatch.setattr(sys, "stdout", captured_stdout)
      monkeypatch.setattr(sys, "stderr", captured_stderr)

      gen = L5XGenerator()
      routine = Routine(name="TestRoutine", type="RLL", rungs=[])
      # Attempt to write to invalid path to trigger exception handler
      result = gen.save_routine_export(routine, str(tmp_path / "nonexistent_dir" / "out.L5X"))

      assert result is False
      assert captured_stdout.getvalue() == "", "BUG-06: stdout was polluted by print()!"
      assert "Error saving routine export" in captured_stderr.getvalue()
  ```

- [ ] **Step 2: Run pytest to verify test fails if stdout is used.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_bug06" -q
  ```

- [ ] **Step 3: Update all unredirected `print()` statements across target files.**
  - In `src/code_generator/l5x_generator.py`: add `file=sys.stderr` to all `print()` calls in exception handlers and `__main__`.
  - In `src/ai_assistant/code_assistant.py`: add `file=sys.stderr` to `print()` calls in `__main__`.
  - In `src/ai_assistant/enhanced_main_assistant.py`: add `file=sys.stderr` to `print()` calls in `__main__`.
  - In `src/drawings_analyzer/pdf_parser.py`: add `file=sys.stderr` to `print()` calls in `__main__`.
  - In `src/documentation/instruction_vector_db.py`: add `file=sys.stderr` to `print()` calls in `__main__`.

- [ ] **Step 4: Run pytest to verify BUG-06 regression test passes.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_bug06" -q
  ```
  Expected result: Test passes.

- [ ] **Step 5: Commit changes for Task 2.**
  ```bash
  git add src/code_generator/l5x_generator.py src/ai_assistant/code_assistant.py src/ai_assistant/enhanced_main_assistant.py src/drawings_analyzer/pdf_parser.py src/documentation/instruction_vector_db.py tests/test_core_bugfixes.py
  git commit -m "Core: fix BUG-06 redirect all prints to stderr to protect MCP JSON-RPC framing"
  ```

---

### Task 3: Fix BUG-07 (Configurable Target Program in `generate_routine_export` and MCP Tool)

**Files:**
- Modify: `src/code_generator/l5x_generator.py:330-374, 386-400`
- Modify: `src/mcp_server/studio5000_mcp_server.py:1209-1320, 1896-1911`
- Modify: `tests/test_core_bugfixes.py`

**Interfaces:**
```python
def generate_routine_export(
    self,
    routine: Routine,
    controller_name: str = "MTN6_MCM06",
    tags: Optional[List[Dict]] = None,
    software_revision: str = "36.02",
    program_name: str = "MainProgram",
    target_program: Optional[str] = None,
) -> str:
    ...
```

- [ ] **Step 1: Write failing regression tests for `target_program` parameter in generator and MCP tool.**
  ```python
  # tests/test_core_bugfixes.py additions
  def test_bug07_generate_routine_export_custom_target_program():
      gen = L5XGenerator()
      routine = Routine(
          name="SafetyStopRoutine",
          type="RLL",
          rungs=[LadderRung(number=0, logic="XIC(E_Stop)OTE(Safety_Fault);")],
      )

      xml_out = gen.generate_routine_export(
          routine=routine,
          target_program="SafetyProgram"
      )

      assert '<Program Use="Context" Name="SafetyProgram" Class="Standard">' in xml_out
      assert 'Name="MainProgram"' not in xml_out
  ```

- [ ] **Step 2: Run pytest to verify test behavior.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_bug07" -q
  ```

- [ ] **Step 3: Update `generate_routine_export` and `save_routine_export` in `src/code_generator/l5x_generator.py`.**
  - Accept both `target_program: Optional[str] = None` and `program_name: str = "MainProgram"`.
  - Resolve effective program name: `effective_program = target_program or program_name`.
  - Inject `effective_program` into `<Program Use="Context" Name="{effective_program}" Class="Standard">`.

- [ ] **Step 4: Update `create_l5x_routine` handler and schema in `src/mcp_server/studio5000_mcp_server.py`.**
  - Extract `target_program = routine_spec.get('target_program') or routine_spec.get('program_name', 'MainProgram')`.
  - Forward `target_program` to `generator.generate_routine_export`.
  - Update `tools/list` schema for `create_l5x_routine` to document `target_program`.

- [ ] **Step 5: Run pytest on all routine export tests.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_bug07" tests/test_code_assistant_and_modernization.py -q
  ```
  Expected result: All tests pass.

- [ ] **Step 6: Commit changes for Task 3.**
  ```bash
  git add src/code_generator/l5x_generator.py src/mcp_server/studio5000_mcp_server.py tests/test_core_bugfixes.py
  git commit -m "Code Generator: fix BUG-07 allow configurable target program in routine exports"
  ```

---

### Task 4: Fix BUG-08 (Generate True 3-Wire Latching Motor Circuits)

**Files:**
- Modify: `src/ai_assistant/code_assistant.py:180-203`
- Modify: `src/code_generator/l5x_generator.py:406-410`
- Modify: `tests/test_core_bugfixes.py`

**Defect & Fix:**
Momentary start pushbuttons require a seal-in latch branch around the start input.
Change from:
`XIC({start_input})XIO({stop_input})OTE({motor_output});`
To:
`[XIC({start_input}) , XIC({motor_output}) ]XIO({stop_input})OTE({motor_output});`

- [ ] **Step 1: Write failing regression test for 3-wire latching start/stop logic.**
  ```python
  # tests/test_core_bugfixes.py additions
  from ai_assistant.code_assistant import CodeAssistant, PLCRequirement

  def test_bug08_start_stop_logic_generates_seal_in_latch():
      assistant = CodeAssistant()
      req = PLCRequirement(
          description="Start stop motor control with start PB, stop PB, and conveyor motor output",
          inputs=["Start_PB", "Stop_PB"],
          outputs=["Motor_Run"],
          system_type="Motor Control",
      )
      code = assistant.generate_code(req)
      assert code.ladder_logic.startswith("[XIC(Start_PB) , XIC(Motor_Run) ]XIO(Stop_PB)OTE(Motor_Run);")
      assert "latch" in code.validation_notes[0].lower() or "three-wire" in code.validation_notes[0].lower()
  ```

- [ ] **Step 2: Run pytest to verify test fails before fix.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_bug08" -q
  ```
  Expected result: AssertionError (missing `[` and seal-in branch).

- [ ] **Step 3: Update `_generate_start_stop_logic` in `src/ai_assistant/code_assistant.py`.**
  ```python
  ladder_logic = f"[XIC({start_input}) , XIC({motor_output}) ]XIO({stop_input})OTE({motor_output});"
  ```
  Update `validation_notes` to `"Standard three-wire seal-in latch motor control circuit"`.
  Update example in `src/code_generator/l5x_generator.py:406-410`.

- [ ] **Step 4: Run pytest to verify BUG-08 test passes.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_bug08" -q
  ```
  Expected result: Test passes.

- [ ] **Step 5: Commit changes for Task 4.**
  ```bash
  git add src/ai_assistant/code_assistant.py src/code_generator/l5x_generator.py tests/test_core_bugfixes.py
  git commit -m "AI Assistant: fix BUG-08 generate standard 3-wire seal-in latch for motor circuits"
  ```

---

### Task 5: Fix Action 13 (Remove Fictitious `PRODUCE` / `CONSUME` Opcodes)

**Files:**
- Modify: `src/ai_assistant/enhanced_ladder_generator.py:75-80`
- Modify: `src/ai_assistant/enhanced_code_assistant.py:490-496`
- Modify: `tests/test_core_bugfixes.py`

**Defect & Fix:**
`PRODUCE` and `CONSUME` are tag connection properties in ControlLogix, not executable ladder instructions. Replace with valid communication opcodes (`MSG`).

- [ ] **Step 1: Write failing regression tests verifying no fictitious instructions in generator tables.**
  ```python
  # tests/test_core_bugfixes.py additions
  from ai_assistant.enhanced_ladder_generator import EnhancedLadderGenerator
  from ai_assistant.enhanced_code_assistant import EnhancedCodeAssistant

  def test_action13_no_produce_consume_ladder_instructions():
      ladder_gen = EnhancedLadderGenerator()
      assert "PRODUCE" not in ladder_gen.comm_mappings.values()
      assert "CONSUME" not in ladder_gen.comm_mappings.values()

      code_ast = EnhancedCodeAssistant()
      assert "PRODUCE" not in code_ast.comm_instructions.values()
      assert "CONSUME" not in code_ast.comm_instructions.values()
  ```

- [ ] **Step 2: Run pytest to verify test fails.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_action13" -q
  ```
  Expected result: AssertionError (PRODUCE and CONSUME found in dictionaries).

- [ ] **Step 3: Update `comm_mappings` and `comm_instructions`.**
  - In `src/ai_assistant/enhanced_ladder_generator.py:75-80`:
    ```python
    self.comm_mappings = {
        'barcode_scanner': 'MSG',     # Message instruction for scanner comm
        'wms_interface': 'MSG',       # Message instruction for WMS interface
        'hmi_update': 'MSG',          # Message/data transfer for HMI
        'plc_to_plc': 'MSG'           # Inter-PLC communication
    }
    ```
  - In `src/ai_assistant/enhanced_code_assistant.py:490-496`:
    ```python
    self.comm_instructions = {
        'message': 'MSG',
        'get_system_value': 'GSV',
        'set_system_value': 'SSV'
    }
    ```

- [ ] **Step 4: Run pytest to verify Action 13 test passes.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -k "test_action13" -q
  ```
  Expected result: Test passes.

- [ ] **Step 5: Commit changes for Task 5.**
  ```bash
  git add src/ai_assistant/enhanced_ladder_generator.py src/ai_assistant/enhanced_code_assistant.py tests/test_core_bugfixes.py
  git commit -m "AI Assistant: remove fictitious PRODUCE/CONSUME ladder opcodes"
  ```

---

### Task 6: Implement Action 19 (Python 3.12 Runtime Version Enforcement Guard)

**Files:**
- Modify: `src/mcp_server/studio5000_mcp_server.py:20-30`
- Modify: `tests/test_core_bugfixes.py`

- [ ] **Step 1: Write unit tests verifying Python version guard behavior.**
  ```python
  # tests/test_core_bugfixes.py additions
  def test_action19_python_version_guard_allows_3_12():
      import sys
      assert sys.version_info[:2] == (3, 12), (
          f"Tests must run under Python 3.12 (current: {sys.version.split()[0]})"
      )
  ```

- [ ] **Step 2: Add version check guard to `src/mcp_server/studio5000_mcp_server.py`.**
  Add immediately after imports:
  ```python
  # Python 3.12 Runtime Version Guard (Action 19 / Issue #5)
  if sys.version_info[:2] != (3, 12):
      sys.stderr.write(
          f"ERROR: Studio 5000 MCP Server requires Python 3.12 (current: {sys.version.split()[0]}). "
          f"Please activate a Python 3.12 virtual environment.\n"
      )
      sys.exit(1)
  ```

- [ ] **Step 3: Run full test suite and MCP server smoke test.**
  ```bash
  python -m pytest tests/test_core_bugfixes.py -q
  python src/mcp_server/studio5000_mcp_server.py --test
  ```
  Expected result: All tests pass; smoke test completes with 0 errors.

- [ ] **Step 4: Commit changes for Task 6.**
  ```bash
  git add src/mcp_server/studio5000_mcp_server.py tests/test_core_bugfixes.py
  git commit -m "MCP Server: enforce Python 3.12 runtime version guard"
  ```
