# Handoff: Human-readable Ignition naming engine

Date: 2026-08-11  
Status: implementation and task-level reviews complete; final whole-branch review is pending.

## Current checkout

- Repository: `F:\git\work\studio5000-AI-Assistant`
- Worktree: `F:\git\work\studio5000-AI-Assistant\.worktrees\human-ignition-naming-engine`
- Branch: `feat/human-ignition-naming-engine`
- Last implementation commit: `30a0885 MCP: expose Ignition human naming options`
- The handoff document itself should be committed as the next commit.

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

Task-level reviews were clean after fixes. One minor item was deferred: the MCP schema regression test does not explicitly assert that `naming_profile_path` is absent from the required list, although the runtime schema is correct.

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

- Focused suite: `82 passed in 1.19s`.
- Full suite excluding the fixture-dependent direct ACD tests: `200 passed, 10 skipped in 1.56s`.
- Unfiltered full suite: `2 failed, 200 passed, 10 skipped in 1.95s`; both failures are the direct ACD tests because the isolated worktree does not contain `tests/acd/ModernTHAWROOM021722.ACD` at the path those tests currently expect.
- MCP smoke test exited `0`; 561 instructions loaded and tools registered. The graph sample was skipped because the corresponding `.L5X` fixture is absent in the isolated worktree.
- `git diff --check` was clean. No generated ACD/L5X/PDF/JSON/vector-cache/profile artifacts were added.

No Studio 5000 or Ignition Designer validation has been performed. Generated SCADA output still requires engineering review and validation in the target Ignition environment.

## Next resume point

1. Re-run the final whole-branch review against the post-handoff HEAD. The interrupted review covered the implementation range `c6a684a..30a0885`; include the handoff commit or explicitly scope the review to implementation commits.
2. Resolve any final review findings before merging.
3. Reconcile the main checkout's existing ACD fixture-path edit without resetting it.
4. Re-run the unfiltered full suite once the expected ACD fixture path is available.
5. Optionally add the deferred schema assertion.
6. Perform Studio 5000/Ignition validation before treating this as deployable.

The workday handoff is complete; leave this worktree and branch preserved for continuation.
