# SPEC-11: Core Reliability Bug Fixes & MCP Protocol Framing

**Status:** Backlog / Sprint 1 Target (BUG-04, BUG-06, BUG-07, BUG-08, BUG-09, Issue #5)  
**Priority:** P1 / High  
**Subsystem:** `code_generator`, `ai_assistant`, `l5x_analyzer`, `mcp_server`  
**Audit References:** [§6 Summary Bug Table](file:///home/hello/git/work/studio5000-AI-Assistant/docs/ENGINEERING_AUDIT_2026.md#summary-bug-table), [§8 Controls Correctness](file:///home/hello/git/work/studio5000-AI-Assistant/docs/ENGINEERING_AUDIT_2026.md#8-industrial-controls--plc-semantic-correctness-findings), [§29 Next Actions #6, #7, #9, #10, #13, #19, #20](file:///home/hello/git/work/studio5000-AI-Assistant/docs/ENGINEERING_AUDIT_2026.md#29-top-25-recommended-next-actions)

---

## 1. Scope of Core Bug Fixes

This specification details the root causes, exact file locations, and implementation fixes for the 6 confirmed core reliability defects in the repository.

---

## 2. Bug Fix Specifications

### 2.1 BUG-04: `get_project_overview` Wrong-Project Fallback
- **File:** `src/l5x_analyzer/l5x_mcp_integration.py:744-754`
- **Issue:** Issue #37
- **Current Defect:** When a requested project stem (e.g. `Kemco_HA105`) is not found in `indexed_projects`, the code falls back to `list(indexed_projects.keys())[0]` and returns the overview of an entirely different project.
- **Fix:**
  ```python
  # Before:
  if project_name not in indexed_projects:
      project_name = list(indexed_projects.keys())[0] # SILENT WRONG PROJECT FALLBACK
  
  # Fixed:
  if project_name not in indexed_projects:
      return {
          "success": False,
          "error": f"Project '{project_name}' is not indexed. Available indexed projects: {list(indexed_projects.keys())}. Run index_exported_l5x_files or index_acd_project first."
      }
  ```

---

### 2.2 BUG-06: Unredirected `print()` Corrupts JSON-RPC stdio Protocol
- **File:** `src/code_generator/l5x_generator.py:326, 393, 469–474`
- **Issue:** Issue #38
- **Current Defect:** Error handlers in the L5X generator call standard `print(...)` to `sys.stdout`. Because the MCP server communicates over standard I/O (`stdio`) using JSON-RPC 2.0 framing, any unformatted text printed to stdout breaks protocol framing and crashes MCP client connections (Claude Desktop, IDEs).
- **Fix:** Redirect all diagnostic messages to `sys.stderr` or use standard Python `logging.getLogger(__name__)`:
  ```python
  import sys
  # Replace: print(f"Error creating routine export: {e}")
  # With:
  print(f"Error creating routine export: {e}", file=sys.stderr)
  ```

---

### 2.3 BUG-07: Hardcoded `MainProgram` in `generate_routine_export`
- **File:** `src/code_generator/l5x_generator.py:329–372`
- **Issue:** Issue #39
- **Current Defect:** `generate_routine_export` generates routine L5X exports wrapped inside a hardcoded `<Program Name="MainProgram">`. If the user attempts to import the routine into a different program (e.g. `SafetyProgram`, `Conveyor_Prog`, or `CIP_Clean`), Studio 5000 rejects the import.
- **Fix:** Add `target_program: str = "MainProgram"` parameter to `generate_routine_export` and `create_l5x_routine` tool schema, allowing callers to target specific program containers.

---

### 2.4 BUG-08: Non-Latching Three-Wire Motor Circuit Generation
- **File:** `src/ai_assistant/code_assistant.py:187-202`
- **Current Defect:** Natural language prompt for a 3-wire start/stop circuit emits:
  ```text
  XIC(START_PB) XIO(STOP_PB) OTE(MOTOR_RUN);
  ```
  In industrial controls, momentary pushbuttons require a seal-in latch branch around the start button:
- **Fix:** Update template to generate true 3-wire latching logic:
  ```text
  [XIC(START_PB) , XIC(MOTOR_RUN) ] XIO(STOP_PB) OTE(MOTOR_RUN);
  ```

---

### 2.5 BUG-09 / Action 13: Remove Fictitious `PRODUCE` / `CONSUME` Instructions
- **File:** `src/ai_assistant/enhanced_ladder_generator.py:77-78`
- **Current Defect:** Motion and communications mapping dictionaries map `'wms_interface'` to `'PRODUCE'` and `'hmi_update'` to `'CONSUME'`. These are not executable ladder instructions in Rockwell PLCs (they are tag connection properties).
- **Fix:** Remove `PRODUCE` and `CONSUME` opcodes from ladder generator templates; map communication transfers to standard `MSG`, `COP`, or `CPS` instructions.

---

### 2.6 Action 19: Python 3.12 Runtime Version Guard
- **File:** `src/mcp_server/studio5000_mcp_server.py:20`
- **Issue:** Issue #5
- **Requirement:** Ensure server exits gracefully with a clear error if executed under unsupported Python versions (e.g. Python 3.14 / Python 3.11):
  ```python
  import sys
  if sys.version_info[:2] != (3, 12):
      sys.stderr.write(
          f"ERROR: Studio 5000 MCP Server requires Python 3.12 (current: {sys.version.split()[0]}). "
          f"Please activate a Python 3.12 virtual environment.\n"
      )
      sys.exit(1)
  ```

---

## 3. Testing & Acceptance Criteria

### 3.1 Unit Tests (`tests/test_core_bugfixes.py`)
- Test `get_project_overview` returns structured error when project missing.
- Test `generate_routine_export` with custom `target_program="ConveyorProgram"`.
- Test ladder generator start/stop logic asserts presence of seal-in branch `[XIC(...) , XIC(...) ]`.
- Test stdio stream integrity during error conditions.

### 3.2 Acceptance Criteria
- All 6 core defects are resolved with passing regression unit tests.
- MCP server smoke test passes with zero stderr protocol pollution.
