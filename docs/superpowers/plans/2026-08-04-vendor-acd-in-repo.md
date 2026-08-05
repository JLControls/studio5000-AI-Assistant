# Vendor Patched ACD Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the MCP’s patched ACD-to-L5X conversion self-contained and validate it against `ModernTHAWROOM021722.ACD`.

**Architecture:** Vendor the patched `acd` Python package under `src/acd` so the existing `PYTHONPATH=...\src` launch resolves it naturally. Keep the MCP converter’s temporary-build compatibility patch, but remove `ACD_TOOLS_SOURCE` and external `sys.path` injection. Preserve the fork’s focused v38 regression tests and Apache provenance.

**Tech Stack:** Python 3.12, pytest, `kaitaistruct`, `loguru`, existing MCP/L5X analyzer, Studio 5000 v38 ACD/L5X artifacts.

## Global Constraints

- Do not modify the source `ModernTHAWROOM021722.ACD` or native `ModernTHAWROOM021722.L5X`.
- Preserve unrelated dirty and untracked worktree changes.
- `STUDIO5000_SDK_ENABLED=false` remains the offline conversion mode.
- The final MCP launch must work without `ACD_TOOLS_SOURCE`.
- Preserve Apache 2.0 licensing and identify the vendored fork commit.

---

### Task 1: Prove the Current External Dependency

**Files:**
- Create: `tests/test_acd_vendoring.py`

- [x] Write a test that imports `acd` with only the repository `src` path and asserts its module path is inside `src/acd`; also assert the converter’s source root is the repository package path rather than an environment-controlled checkout.
- [x] Run `python -m pytest tests/test_acd_vendoring.py -q` with `PYTHONPATH=src` and confirm it fails because `src/acd` does not exist.

### Task 2: Vendor the Patched Runtime

**Files:**
- Create: `src/acd/**` from `F:\git\work\acd\acd\**`
- Create: `tests/acd/test_comments_v38.py`
- Create: `tests/acd/test_regn_link.py`
- Create: `THIRD_PARTY_LICENSES.md`

- [x] Copy the complete importable `acd` package, including generated Kaitai modules and package initializers, but exclude `__pycache__` and build metadata.
- [x] Copy the two fork tests and adapt only imports/fixture paths needed for this repository’s test layout.
- [x] Record fork commit `038d120d9f568aa371a7f029c4f740f20fad7276`, upstream origin, Apache 2.0 license, and the three patched runtime files.
- [x] Add `kaitaistruct` and `loguru` to `requirements.txt`.
- [x] Run the focused tests and confirm they pass.

### Task 3: Remove External Path Coupling

**Files:**
- Modify: `src/l5x_analyzer/acd_offline_convert.py`
- Modify: `requirements.txt`
- Modify: `README.md`
- Modify: `AGENTS.md`

- [x] Resolve the vendored package from the repository’s `src` tree and delete `_ACD_SOURCE`, `ACD_TOOLS_SOURCE`, and `_load_acd_source()`.
- [x] Keep the exporter compatibility patch and make `convert_acd_to_l5x()` import the vendored `acd.api` directly.
- [x] Document the self-contained setup and remove instructions implying an external ACD checkout.
- [x] Run the dependency test with `ACD_TOOLS_SOURCE` unset and verify it still passes.

### Task 4: Validate the Real MCP Conversion

**Files:**
- Create outside the repository: `ModernTHAWROOM021722.Offline.Vendored.L5X`

- [x] Launch the repository venv with `PYTHONPATH=...\src`, `STUDIO5000_SDK_ENABLED=false`, and no `ACD_TOOLS_SOURCE`.
- [x] Call the MCP conversion path against the supplied ACD and write output outside the source directory.
- [x] Parse the generated L5X as XML and compare inventory/semantic results with the native Studio export.
- [x] Confirm conversion success, output existence, and no regressions in the patched comment/rung behavior; report any known fidelity gap rather than treating offline output as import-safe automatically.

### Task 5: Final Verification

- [x] Run all focused vendored tests and the repository MCP smoke test if its local documentation dependencies are available.
- [x] Run `git diff --check` and review `git status`; preserve unrelated pre-existing edits and record their whitespace/environment warnings separately.
- [x] Do not commit unless explicitly requested.
