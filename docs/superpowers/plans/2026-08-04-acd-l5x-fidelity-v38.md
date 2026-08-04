# ACD to L5X Fidelity for Studio 5000 v38 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the highest-fidelity offline L5X available from ACD files and expose semantic losses clearly, with SDK integration disabled.

**Architecture:** Pin upstream `hutcheb/acd`, keep only non-destructive compatibility patches, convert ACD to L5X before indexing, and compare generated XML semantically with a native Studio export.

**Tech Stack:** Python 3.12, `hutcheb/acd`, `unittest`, XML ElementTree, PowerShell, MCP.

## Global Constraints

- Target Studio 5000 v38.
- Do not initialize or call the Logix Designer SDK.
- Preserve existing uncommitted integration work.
- Treat Studio-exported L5X as the semantic oracle only when it matches the ACD revision.

---

### Task 1: Rung comment regression

**Files:**
- Create: `tests/test_acd_l5x_fidelity.py`
- Modify: `src/l5x_analyzer/acd_offline_convert.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `convert_acd_to_l5x(input_path, output_path, pretty)`.
- Produces: L5X containing upstream `Comments.Dat` rung comments.

- [ ] Add a real-fixture test comparing non-empty rung comments by program, routine, and rung number.
- [ ] Run it against the current converter and confirm the missing-comment failure.
- [ ] Pin upstream commit `019fb7872e090f71fc11313b5b98ed468a92cc75`.
- [ ] Remove or adapt routine monkey patches so upstream comment state survives while rung ordering remains correct.
- [ ] Re-run the test and confirm it passes.

### Task 2: Semantic parity reporting

**Files:**
- Create: `src/l5x_analyzer/l5x_semantic_validation.py`
- Modify: `src/l5x_analyzer/acd_offline_convert.py`
- Modify: `tests/test_acd_l5x_fidelity.py`

**Interfaces:**
- Produces: `compare_l5x(generated_path, reference_path) -> dict` and conversion `validation` metrics.

- [ ] Add failing tests for rung text, tag documentation, programs, routines, data types, AOIs, and modules.
- [ ] Implement semantic inventory and keyed comparisons.
- [ ] Return explicit losses and warnings from conversion.
- [ ] Run all regression tests.

### Task 3: Disable SDK-backed ACD operations

**Files:**
- Modify: `src/l5x_analyzer/l5x_vector_db.py`
- Modify: `src/mcp_server/studio5000_mcp_server.py`
- Modify: `.vscode/scripts/drivers/convert_acd_to_l5x.ps1`
- Modify: `.vscode/scripts/drivers/convert_all_acd_to_l5x.ps1`

**Interfaces:**
- ACD indexing converts offline, then indexes L5X.
- SDK project tools are not registered or called.

- [ ] Add failing tests or controlled harness checks proving ACD indexing does not open the SDK.
- [ ] Route indexing through offline conversion.
- [ ] Remove SDK-first behavior from PowerShell conversion tasks.
- [ ] Verify MCP tool discovery and conversion.

### Task 4: Dependency and repository guidance

**Files:**
- Modify: `requirements.txt`
- Modify: `.vscode` dependency installation scripts.
- Modify or create repository `AGENTS.md` conversion guidance.

**Interfaces:**
- Every converter uses the same pinned upstream commit and intended venv.

- [ ] Replace unpinned `acd-tools` installs with the tested Git commit.
- [ ] Document the v38 target, offline fidelity boundary, and parity command.
- [ ] Run the full thaw-room conversion and semantic comparison.
- [ ] Review diffs and report all remaining losses.
