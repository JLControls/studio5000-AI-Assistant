# Safe Modification Staging & Unified-Diff Preview Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Partial implementation. The repository still has direct L5X writes in `smart_insert_logic`; the staging boundary is not complete until L5X and ACD mutators share the same review/apply contract.

**Goal:** Implement a secure, two-phase mutation staging and unified-diff preview engine (`stage_insert_logic`, `stage_patch_rungs`, `stage_patch_comments`, `apply_staged_change`, `discard_staged_change`) that prevents blind disk mutations and binds approval to an exact target and diff digest.

**Architecture:** The engine introduces an in-memory staging store (`StagingStore`) that holds parsed, validated, and mutated AST state. When a modification is requested, the target file's current SHA-256 hash is computed, the AST is modified in memory, syntax validation is executed, dual unified diffs (`visual_rll_diff` and `xml_unified_diff`) are rendered via `difflib`, and a cryptographically random UUIDv4 `change_token` is returned with an impact summary. Disk writes are strictly prohibited during staging. Committing changes via `apply_staged_change` verifies that the target file's hash on disk has not changed concurrently, creates an uncompressed timestamped `.bak` backup copy, and writes the validated payload atomically.

**Tech Stack:** Python 3.12, standard library `hashlib`, `uuid`, `time`, `difflib`, `shutil`, `tempfile`, `xml.etree.ElementTree`, `dataclasses`, `rll_parser`, MCP JSON-RPC protocol, pytest.

---

## Global Constraints

- **Never Mutate on First Call:** No modification tool (`smart_insert_logic`, `stage_insert_logic`, `patch_rungs`) may write bytes to disk without an explicit human review gate and approval step.
- **Cryptographic SHA-256 Binding:** Staging tokens are strictly bound to the target file's SHA-256 hash at staging time. If the file is modified externally or concurrently prior to `apply_staged_change`, the token is rejected with `FileModifiedConcurrentlyError`.
- **Dual Diff Representation:**
  - `visual_rll_diff`: Unified diff format displaying human-readable ladder logic rungs with `+` (added), `-` (removed), and ` ` (context) lines.
  - `xml_unified_diff`: Standard unified diff format showing raw XML/CDATA differences.
- **Mandatory Backup Copies:** Every committed change via `apply_staged_change` must create a uniquely named backup in the same directory before writing to disk. Use timestamp plus a collision-resistant suffix; a second commit in the same second must not overwrite the first backup.
- **Atomic Disk Writes:** Mutations must write to a temporary file on the same filesystem and replace the target file atomically via `os.replace` to prevent corrupted partial writes.
- **In-Memory TTL & Eviction:** Staged changes expire after 1 hour (configurable TTL) and are evicted immediately upon being applied or discarded.
- **Process boundary:** An in-memory token is valid only in the issuing server process. If restart/multiprocess use is required, add a durable signed token store and key-rotation design; do not imply restart persistence from an in-memory TTL.
- **Format boundary:** `stage_insert_logic` must not claim to cover `patch_rungs` or `edit_acd` until equivalent ACD staging is implemented. ElementTree reserialization is an XML-semantic diff, not a byte-preserving diff; label it accordingly.
- **Engineering Review Mandatory:** Generated diffs and staged logic require human review and Studio 5000 Logix Designer verification before deployment to live physical controllers.

---

## File Map

### Create:
- `src/l5x_analyzer/staging_diff_engine.py` — Pure staging store, AST mutation engine, dual diff generator, SHA-256 hashing, and atomic commit/backup engine.
- `tests/l5x_analyzer/test_staging_diff.py` — Unit and integration tests covering staging, dual diff generation, concurrency conflict detection, backup creation, atomic commits, token expiration, and MCP tool handling.

### Modify:
- `src/l5x_analyzer/l5x_mcp_integration.py` — Add `stage_insert_logic`, `stage_patch_rungs`, `stage_patch_comments`, `apply_staged_change`, `discard_staged_change` methods, and route/fail-closed blind direct mutations in `smart_insert_logic`.
- `src/mcp_server/studio5000_mcp_server.py` — Register `stage_insert_logic`, `apply_staged_change`, `discard_staged_change` tools in `_register_tools()`, implement delegator methods, and update JSON-RPC `tools/list` schema.
- `tests/test_mcp_workaround_fixes.py` — Add MCP schema tests for `stage_insert_logic` and `apply_staged_change`.

### Do Not Modify:
- `tests/test_direct_acd_deliverables.py` (pre-existing worktree modification).
- Unrelated vector database modules.

---

## Data Models & Type Specifications

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import time

class InsertionMode(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    REPLACE = "REPLACE"

class ValidationStatus(str, Enum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"

@dataclass
class StagedChange:
    change_token: str                  # UUIDv4 identifier
    target_file_path: str             # Normalized absolute path
    target_sha256: str                 # SHA-256 hex digest of file at staging time
    diff_sha256: str                   # SHA-256 digest of the exact returned diff payload
    created_timestamp: str             # ISO 8601 creation timestamp
    routine_name: str
    program_name: Optional[str]
    insertion_mode: str                # "BEFORE", "AFTER", "REPLACE"
    target_rung_number: int
    rungs_added: int
    rungs_modified: int
    rungs_deleted: int
    visual_rll_diff: str               # Human-readable ladder text diff
    xml_unified_diff: str              # XML unified diff
    validation_status: str             # "PASSED", "WARNING", "FAILED"
    validation_errors: List[str]       # Validation diagnostic messages
    staged_payload_bytes: bytes        # UTF-8 encoded XML bytes ready to commit
    expires_at: float                  # Epoch timestamp for TTL expiration
```

---

## Tasks & Execution Steps

### Task 1: Implement In-Memory Staging, AST Mutation, and Dual Diff Generation

**Files:**
- Create: `src/l5x_analyzer/staging_diff_engine.py`
- Create: `tests/l5x_analyzer/test_staging_diff.py`

- [ ] **Step 1: Write failing unit tests for staging and diff generation.**
  Test that staging an insertion does NOT modify the target file on disk, computes valid SHA-256 hashes, generates visual RLL text diffs with `+`/`-` markers, and creates valid XML diffs.

  ```python
  # tests/l5x_analyzer/test_staging_diff.py
  import os, shutil, tempfile, pytest
  from pathlib import Path
  from l5x_analyzer.staging_diff_engine import StagingDiffEngine, InsertionMode

  SAMPLE_L5X = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
  <RSLogix5000Content SchemaRevision="1.0" TargetName="Test" TargetType="Controller" ContainsContext="true">
    <Controller Use="Context" Name="TestController">
      <Programs>
        <Program Use="Context" Name="MainProgram">
          <Routines>
            <Routine Use="Context" Name="MainRoutine" Type="RLL">
              <RLLContent>
                <Rung Number="0" Type="N">
                  <Comment><![CDATA[Rung 0 comment]]></Comment>
                  <Text><![CDATA[XIC(TagA) OTE(TagB);]]></Text>
                </Rung>
                <Rung Number="1" Type="N">
                  <Comment><![CDATA[Rung 1 comment]]></Comment>
                  <Text><![CDATA[XIC(TagC) OTE(TagD);]]></Text>
                </Rung>
              </RLLContent>
            </Routine>
          </Routines>
        </Program>
      </Programs>
    </Controller>
  </RSLogix5000Content>
  """

  @pytest.fixture
  def temp_l5x(tmp_path):
      file_path = tmp_path / "test_project.L5X"
      file_path.write_text(SAMPLE_L5X, encoding="utf-8")
      return file_path

  def test_stage_insertion_does_not_modify_disk(temp_l5x):
      initial_bytes = temp_l5x.read_bytes()
      engine = StagingDiffEngine()
      result = engine.stage_insert_logic(
          file_path=str(temp_l5x),
          routine_name="MainRoutine",
          target_rung_number=0,
          insertion_mode="AFTER",
          rll_text="XIC(TagE) OTE(TagF);",
          program_name="MainProgram",
          rung_comment="New staged rung",
      )
      assert result["success"] is True
      assert "change_token" in result
      assert result["diff"]["rungs_added"] == 1
      assert temp_l5x.read_bytes() == initial_bytes  # Disk untouched!

  def test_visual_and_xml_diff_generation(temp_l5x):
      engine = StagingDiffEngine()
      result = engine.stage_insert_logic(
          file_path=str(temp_l5x),
          routine_name="MainRoutine",
          target_rung_number=0,
          insertion_mode="AFTER",
          rll_text="XIC(TagE) OTE(TagF);",
          program_name="MainProgram",
      )
      visual_diff = result["diff"]["visual_rll_diff"]
      xml_diff = result["diff"]["xml_unified_diff"]

      assert "+ [Rung 1] XIC(TagE) OTE(TagF);" in visual_diff
      assert "+      <Rung Number=\"1\" Type=\"N\">" in xml_diff
  ```

- [ ] **Step 2: Run pytest to verify initial failure.**
  ```powershell
  python -m pytest tests/l5x_analyzer/test_staging_diff.py -q
  ```
  *Expected:* Import failure because `src/l5x_analyzer/staging_diff_engine.py` does not exist.

- [ ] **Step 3: Implement core `StagingDiffEngine` and `StagedChange` in `src/l5x_analyzer/staging_diff_engine.py`.**
  - Implement `StagedChange` dataclass and thread-safe `_StagingStore` with TTL expiration (default 3600 seconds).
  - Implement SHA-256 file hashing: `hashlib.sha256(file_path.read_bytes()).hexdigest()`.
  - Implement in-memory XML parsing and routine rung extraction:
    - Extract routine rungs as formatted strings: `f"[Rung {num}] {comment_str}{rll_text}"`.
    - Apply AST modifications:
      - `AFTER`: Insert after `target_rung_number`, renumber subsequent rungs.
      - `BEFORE`: Insert before `target_rung_number`, renumber existing rungs.
      - `REPLACE`: Replace `target_rung_number`, retain or adjust subsequent rung numbers.
  - Implement unified diff generation using `difflib.unified_diff` for both visual RLL text and XML text.
  - Generate UUIDv4 token `str(uuid.uuid4())`, store in `_StagingStore`, and return detailed preview response.

- [ ] **Step 4: Run tests and verify staging passes.**
  ```powershell
  python -m pytest tests/l5x_analyzer/test_staging_diff.py -q
  ```

---

### Task 2: Implement Validation, Concurrency Guard, Backup Creation, and Atomic Commit

**Files:**
- Modify: `src/l5x_analyzer/staging_diff_engine.py`
- Modify: `tests/l5x_analyzer/test_staging_diff.py`

- [ ] **Step 1: Add failing unit tests for commit, backup, concurrency conflict, and discard.**

  ```python
  # tests/l5x_analyzer/test_staging_diff.py
  from l5x_analyzer.staging_diff_engine import FileModifiedConcurrentlyError

  def test_apply_staged_change_commits_and_creates_backup(temp_l5x):
      engine = StagingDiffEngine()
      stage_res = engine.stage_insert_logic(
          file_path=str(temp_l5x),
          routine_name="MainRoutine",
          target_rung_number=0,
          insertion_mode="AFTER",
          rll_text="XIC(TagE) OTE(TagF);",
          program_name="MainProgram",
      )
      token = stage_res["change_token"]
      apply_res = engine.apply_staged_change(
          token,
          target_sha256=stage_res["target_sha256"],
          diff_sha256=stage_res["diff_sha256"],
      )

      assert apply_res["success"] is True
      assert apply_res["backup_created"] is not None
      assert os.path.exists(apply_res["backup_created"])
      assert "XIC(TagE) OTE(TagF);" in temp_l5x.read_text(encoding="utf-8")

  def test_apply_staged_change_rejects_concurrent_modifications(temp_l5x):
      engine = StagingDiffEngine()
      stage_res = engine.stage_insert_logic(
          file_path=str(temp_l5x),
          routine_name="MainRoutine",
          target_rung_number=0,
          insertion_mode="AFTER",
          rll_text="XIC(TagE) OTE(TagF);",
          program_name="MainProgram",
      )
      token = stage_res["change_token"]

      # Simulate external modification on disk
      temp_l5x.write_text(temp_l5x.read_text(encoding="utf-8") + "<!-- Modified -->", encoding="utf-8")

      apply_res = engine.apply_staged_change(
          token,
          target_sha256=stage_res["target_sha256"],
          diff_sha256=stage_res["diff_sha256"],
      )
      assert apply_res["success"] is False
      assert "concurrently" in apply_res["error"].lower()

  def test_discard_staged_change(temp_l5x):
      engine = StagingDiffEngine()
      stage_res = engine.stage_insert_logic(
          file_path=str(temp_l5x),
          routine_name="MainRoutine",
          target_rung_number=0,
          insertion_mode="AFTER",
          rll_text="XIC(TagE) OTE(TagF);",
          program_name="MainProgram",
      )
      token = stage_res["change_token"]
      discard_res = engine.discard_staged_change(token)
      assert discard_res["success"] is True

      # Applying discarded token should fail
      apply_res = engine.apply_staged_change(
          token,
          target_sha256=stage_res["target_sha256"],
          diff_sha256=stage_res["diff_sha256"],
      )
      assert apply_res["success"] is False
  ```

- [ ] **Step 2: Implement validation and atomic commit logic in `src/l5x_analyzer/staging_diff_engine.py`.**
  - **Syntax Validation:** Validate ladder text using `rll_parser.find_calls`:
    - Ensure balanced parentheses and square brackets.
    - Validate that rung ends with semicolon `;`.
    - Ensure at least one instruction is present.
    - If errors found, mark `validation_status="FAILED"` and return errors in staging result.
  - **Concurrency Conflict Guard:**
    - In `apply_staged_change`, re-read target file from disk and compute current SHA-256.
    - If `current_sha256 != staged.target_sha256`: return error: `Target file '{path}' has been modified concurrently since change token was issued. Stage the modification again.`
  - **Backup Generator:**
    - Generate timestamp plus a collision-resistant suffix.
    - Target backup path: `<dir>/<stem>_<timestamp>_<unique>.bak`; refuse to overwrite an existing backup.
    - Copy original file to backup using `shutil.copy2`.
  - **Atomic Commit:**
    - Write `staged.staged_payload_bytes` to a named temporary file in the same directory as the target file.
    - Flush and sync to disk.
    - Atomically rename temporary file over `target_file_path` using `os.replace`.
    - Evict token from staging store.

- [ ] **Step 3: Run pytest and verify all commit, backup, and conflict tests pass.**
  ```powershell
  python -m pytest tests/l5x_analyzer/test_staging_diff.py -q
  ```

---

### Task 3: MCP Server Integration & Deprecation of Blind Mutations

**Files:**
- Modify: `src/l5x_analyzer/l5x_mcp_integration.py`
- Modify: `src/mcp_server/studio5000_mcp_server.py`
- Modify: `tests/test_mcp_workaround_fixes.py`

- [ ] **Step 1: Write failing MCP schema tests for `stage_insert_logic`, `apply_staged_change`, and `discard_staged_change`.**

  ```python
  # tests/test_mcp_workaround_fixes.py
  import asyncio
  from mcp_server.studio5000_mcp_server import Studio5000MCPServer, handle_mcp_request

  def test_staging_tools_mcp_schema():
      server = Studio5000MCPServer(doc_root=".")
      response = asyncio.run(handle_mcp_request(
          server, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
      ))
      tools = {t["name"]: t for t in response["result"]["tools"]}

      assert "stage_insert_logic" in tools
      assert "apply_staged_change" in tools
      assert "discard_staged_change" in tools

      stage_props = tools["stage_insert_logic"]["inputSchema"]["properties"]
      assert "insertion_mode" in stage_props
      assert stage_props["insertion_mode"]["enum"] == ["BEFORE", "AFTER", "REPLACE"]
      assert tools["stage_insert_logic"]["inputSchema"]["required"] == [
          "file_path", "routine_name", "target_rung_number", "rll_text"
      ]

      apply_props = tools["apply_staged_change"]["inputSchema"]["properties"]
      assert "change_token" in apply_props
      assert "create_backup" not in apply_props
      assert tools["apply_staged_change"]["inputSchema"]["required"] == [
          "change_token", "target_sha256", "diff_sha256"
      ]
  ```

- [ ] **Step 2: Update `src/l5x_analyzer/l5x_mcp_integration.py`.**
  - Instantiate a persistent `StagingDiffEngine` instance on `L5XSDKMCPIntegration`.
  - Add async methods: `stage_insert_logic`, `apply_staged_change`, `discard_staged_change`.
  - Update `smart_insert_logic`: route through staging or fail closed with a deprecation response; a warning followed by a direct write does not satisfy the safety contract.

- [ ] **Step 3: Update `src/mcp_server/studio5000_mcp_server.py`.**
  - Register `stage_insert_logic`, `apply_staged_change`, and `discard_staged_change` in `_register_tools()`.
  - Implement delegation methods on `Studio5000MCPServer`.
  - Add `elif name in ('stage_insert_logic', 'apply_staged_change', 'discard_staged_change'):` schema blocks in `tools/list` handler.

- [ ] **Step 4: Run MCP surface and schema tests.**
  ```powershell
  python -m pytest tests/test_mcp_workaround_fixes.py tests/l5x_analyzer/test_staging_diff.py -q
  ```

---

### Task 4: End-to-End Workflow Verification & Acceptance Tests

**Files:**
- Modify: `tests/l5x_analyzer/test_staging_diff.py`

- [ ] **Step 1: Write complete end-to-end workflow test via MCP JSON-RPC protocol.**
  1. Call `stage_insert_logic` over a test L5X file.
  2. Inspect returned `change_token`, `visual_rll_diff`, and `xml_unified_diff`.
  3. Verify target file on disk is unchanged.
  4. Call `apply_staged_change` with `change_token`.
  5. Verify `.bak` backup file exists on disk.
  6. Verify modified L5X on disk parses cleanly with `xml.etree.ElementTree` and contains the inserted rung.

- [ ] **Step 2: Run full repository test suite.**
  ```powershell
  python -m pytest -q
  ```
  *Expected:* 100% pass across all unit and integration test suites.

- [ ] **Step 3: Run MCP Server Smoke Test.**
  ```powershell
  python src/mcp_server/studio5000_mcp_server.py --test
  ```
  *Expected:* Server starts, indexes docs, tests tool registration (including `stage_insert_logic` and `apply_staged_change`), and completes smoke test queries.

---

## MCP Schemas

### 1. `stage_insert_logic`
```json
{
  "name": "stage_insert_logic",
  "description": "Generates a proposed logic insertion in memory, validates ladder syntax, and returns dual unified diffs (visual RLL + XML) and a secure change token for human review without modifying disk.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "file_path": {
        "type": "string",
        "description": "Path to the .L5X project file."
      },
      "routine_name": {
        "type": "string",
        "description": "Target routine name."
      },
      "target_rung_number": {
        "type": "integer",
        "description": "0-based target rung number in the routine."
      },
      "rll_text": {
        "type": "string",
        "description": "Ladder logic text to insert (e.g. 'XIC(TagA) OTE(TagB);')."
      },
      "program_name": {
        "type": "string",
        "default": "MainProgram",
        "description": "Parent program name (defaults to 'MainProgram')."
      },
      "insertion_mode": {
        "type": "string",
        "enum": ["BEFORE", "AFTER", "REPLACE"],
        "default": "AFTER",
        "description": "Insertion mode relative to target_rung_number."
      },
      "rung_comment": {
        "type": "string",
        "description": "Optional documentation comment for the rung."
      }
    },
    "required": ["file_path", "routine_name", "target_rung_number", "rll_text"]
  }
}
```

### 2. `apply_staged_change`
```json
{
  "name": "apply_staged_change",
  "description": "Commits a previously reviewed and approved staged logic change to disk after verifying the target file SHA-256 hash and generating a timestamped .bak backup copy.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "change_token": {
        "type": "string",
        "description": "UUIDv4 change token returned by stage_insert_logic."
      },
      "target_sha256": {
        "type": "string",
        "description": "Expected target digest returned by staging; prevents applying to a different file."
      },
      "diff_sha256": {
        "type": "string",
        "description": "Expected reviewed diff digest returned by staging; binds approval to the displayed change."
      }
    },
    "required": ["change_token", "target_sha256", "diff_sha256"]
  }
}
```

### 3. `discard_staged_change`
```json
{
  "name": "discard_staged_change",
  "description": "Explicitly discards a staged change token from memory without applying changes to disk.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "change_token": {
        "type": "string",
        "description": "UUIDv4 change token to discard."
      }
    },
    "required": ["change_token"]
  }
}
```

---

## Verification & Acceptance Checklist

- [ ] Zero bytes are written to target files during `stage_insert_logic`.
- [ ] `stage_insert_logic` returns both `visual_rll_diff` (human-readable ladder text) and `xml_unified_diff`.
- [ ] Staging tokens are cryptographically bound to target file SHA-256; concurrent file edits cause `apply_staged_change` to abort safely.
- [ ] Applying a staged change creates a timestamped `.bak` backup copy.
- [ ] Backup names cannot collide, and no caller can disable the backup through the MCP schema.
- [ ] `stage_insert_logic`, `stage_patch_rungs`, and `stage_patch_comments` all return the same target/diff digests and use the same apply path.
- [ ] Commits use atomic file replacement (`os.replace`) to prevent file corruption.
- [ ] All unit and integration tests in `tests/l5x_analyzer/test_staging_diff.py` pass.
- [ ] MCP smoke test `python src/mcp_server/studio5000_mcp_server.py --test` runs cleanly.
