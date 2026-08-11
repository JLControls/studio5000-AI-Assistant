# Handoff: Human-readable Ignition naming engine

Date: 2026-08-11  
Status: implementation complete; final whole-branch review clean. Studio 5000/Ignition validation remains external.

## Current checkout

- Repository: `F:\git\work\studio5000-AI-Assistant`
- Worktree: `F:\git\work\studio5000-AI-Assistant\.worktrees\human-ignition-naming-engine`
- Branch: `feat/human-ignition-naming-engine`
- Last implementation commit: `3eba34c Ignition: sanitize before human name disambiguation`
- Handoff commit: `661ef11 docs: add Ignition naming handoff`

The main checkout contains a pre-existing user edit in `tests/test_direct_acd_deliverables.py` that changes the fixture path to `tests/acd/ModernTHAWROOM021722/ModernTHAWROOM021722.ACD`. It was deliberately left untouched. Do not overwrite or reset that edit.

## What was implemented

The branch adds a deterministic, profile-driven human naming engine for Ignition exports.

- Added the pure naming engine, profile loader, defaults, and corpus fixture.
- Preserved raw naming as the default behavior.
- Integrated `naming="human"` into Ignition tag export, including profile loading, presentation overrides, tooltip precedence, root handling, and telemetry fields.
- Exposed `naming` and `naming_profile_path` through the MCP handler and schema.
- Added focused engine, exporter, override, parity, and MCP regression tests.

Example configuration:

```json
{
  "naming": "human",
  "naming_profile_path": "C:\\project\\ignition-naming-profile.json"
}
```

## Commits in the implementation branch

- `43c70af` Ignition: add deterministic naming engine
- `606cd34` Ignition: preserve curve points and profile tests
- `1869bbe` Ignition: restore generic test marker detection
- `4d1216d` Ignition: integrate human naming into tag export
- `45c80c0` Ignition: address human naming review findings
- `30a0885` MCP: expose Ignition human naming options
- `2558454` Ignition: disambiguate overridden human names
- `3eba34c` Ignition: sanitize before human name disambiguation

Task-level and final whole-branch reviews are clean after fixes. The MCP schema regression now asserts that both naming parameters are optional. Human-mode overrides are sanitized before collision disambiguation, including collisions such as `A/B` versus `A B`.

## Verification evidence

Run from the isolated worktree with the shared repository virtual environment:

```powershell
Set-Location F:\git\work\studio5000-AI-Assistant\.worktrees\human-ignition-naming-engine
$py = 'F:\git\work\studio5000-AI-Assistant\venv\Scripts\python.exe'
& $py -m pytest tests\ignition_exporter tests\test_mcp_workaround_fixes.py -q
& $py -m pytest -q --ignore=tests\test_direct_acd_deliverables.py
& $py src\mcp_server\studio5000_mcp_server.py --test
```

Recorded results:

- Focused suite: `84 passed`.
- Full suite excluding the fixture-dependent direct ACD tests: `202 passed, 10 skipped`.
- Unfiltered full suite: `2 failed, 200 passed, 10 skipped in 1.95s`; both failures are the direct ACD tests because the isolated worktree does not contain `tests/acd/ModernTHAWROOM021722.ACD` at the path those tests currently expect.
- MCP smoke test exited `0`; 561 instructions loaded and tools registered. The graph sample was skipped because the corresponding `.L5X` fixture is absent in the isolated worktree.
- `git diff --check` was clean. No generated ACD/L5X/PDF/JSON/vector-cache/profile artifacts were added.

No Studio 5000 or Ignition Designer validation has been performed. Generated SCADA output still requires engineering review and validation in the target Ignition environment.

## Next resume point

1. Reconcile the main checkout's existing ACD fixture-path edit without resetting it.
2. Re-run the unfiltered full suite once the expected ACD fixture path is available.
3. Perform Studio 5000/Ignition validation before treating this as deployable.

The workday handoff is complete; leave this worktree and branch preserved for continuation.
