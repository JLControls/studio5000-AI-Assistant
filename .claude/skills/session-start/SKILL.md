---
name: session-start
description: Use when beginning work in JLControls/studio5000-AI-Assistant that may edit code, tests, repository skills, generated PLC artifacts, or configuration before a governing GitHub issue has been established.
---

# Session start — anchor changes to a GitHub Issue

Every session that may change this repository must be anchored to a GitHub Issue before the first edit. This keeps work traceable and exposes overlapping work before two sessions modify the same behavior.

Use this repository explicitly in every GitHub CLI command:

```powershell
$repo = "JLControls/studio5000-AI-Assistant"
```

Do not rely on the current `gh` repository context: this checkout may also have an `upstream` remote for `rivie13/studio5000-AI-Assistant`.

## Step 0 — Establish repository context

Before editing:

- Read `AGENTS.md` and the relevant package guidance.
- Run `git status --short --branch` and preserve existing user changes.
- Run `git remote -v` and confirm the intended target is `JLControls/studio5000-AI-Assistant`.
- Identify the exact files and tests likely to be affected.

## Step 1 — Map the task to area labels

Choose every applicable existing `area:*` label:

| Work involves | Label |
|---|---|
| Vendored ACD parser/exporter, direct ACD tools, `tests/acd/` | `area:acd` |
| L5X search, structure analysis, or insertion (`src/l5x_analyzer/`) | `area:l5x_analyzer` |
| Ladder/L5X generation (`src/code_generator/`) | `area:code_generator` |
| Ignition export (`src/ignition_exporter/`) | `area:ignition_exporter` |
| MCP server, tag/comment analysis, drawings, rendering, verification, docs, or repository skills | `area:ai_assistant` |
| Python version, dependencies, test environment, or environment regression tests | `area:env-tests` |

The repository uses `type:bug`, `type:feature`, `severity:*`, and `area:*` labels. Do not invent the copied project’s `area/...`, `work-item`, or `status/in-progress` labels.

If the task spans areas, list all of them in the issue and session comment. Use the primary area in the commit scope and include all governing issue references.

## Step 2 — List open issues

```powershell
$repo = "JLControls/studio5000-AI-Assistant"
gh issue list --repo $repo --label "area:<area>" --state open --json number,title,labels,updatedAt --limit 20
gh issue list --repo $repo --label "type:bug" --state open --json number,title,labels,updatedAt --limit 50
```

Search issue titles and bodies for the affected file, tool, package, and user-visible behavior when the area list is broad. Project Status is not necessarily exposed by `gh issue list`; inspect issue comments and the GitHub Project when an active-work decision matters.

## Step 3 — Identify the governing issue

Choose the best match:

- **Exact match** — use the open issue whose scope is this task.
- **Partial match** — use the issue that will be advanced, and state the partial scope in the session-start comment.
- **No match** — create one with an existing type and area label:

```powershell
$repo = "JLControls/studio5000-AI-Assistant"
$body = @"
## What

<what changes and why>

## Acceptance

- [ ] <first verifiable outcome>
- [ ] Tests or validation pass
"@
gh issue create --repo $repo --title "<verb>: <what>" --label "type:feature" --label "area:<area>" --body $body
```

Record the issue number as `#NNN` for the rest of the session. Add the `documentation` label for documentation-only work when appropriate.

For work that advances a closed issue, reopen it and comment why rather than creating a duplicate:

```powershell
gh issue reopen NNN --repo $repo
gh issue comment NNN --repo $repo --body "Reopening for: <what is changing>."
```

## Step 4 — Check for in-progress conflicts

The repository does not currently define a `status/in-progress` issue label. Therefore, an empty label query does not prove that no one is working on the area.

For each plausible overlapping issue, inspect its body, comments, linked pull requests, and Project Status:

```powershell
gh issue view NNN --repo $repo --comments
```

If an overlapping issue has an active session comment, an in-progress Project Status, or a linked change touching the same files or logic, stop and coordinate before editing. Otherwise record the checked issues in the session-start comment.

## Step 5 — Post the session-start comment

```powershell
$repo = "JLControls/studio5000-AI-Assistant"
$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mmZ")
$body = @"
**Session start** — $stamp

Task: <one sentence>
Files in scope: `<file1>`, `<file2>` (or 'TBD if exploratory')
Related open issues checked: #X (<title>), #Y (<title>) — or 'none'
"@
gh issue comment NNN --repo $repo --body $body
```

This comment is the handoff record for the next session. Include the actual files, the issue number, and any partial scope or conflict decision.

## Step 6 — Emit the session context block

Include this at the top of the first substantive response:

```
── Session context ─────────────────────────────────────────
Governing issue : #NNN — <title>
Related open    : #X (area:...) — <why it might cross-cut>
                  [or 'none checked']
Commit prefix   : <type>(<area>): ... [Refs #NNN]
────────────────────────────────────────────────────────────
```

Use `Refs #NNN` in commits that advance an issue. Use `Closes #NNN` only in the final commit that fully resolves it.

## Repository-specific safeguards

- Use the repository Python 3.12 environment for tests; run `python -m pytest` and the MCP smoke test after server changes.
- Treat generated PLC logic as requiring engineering review and Studio 5000 validation before deployment.
- Native L5X remains authoritative for deployment decisions. Do not commit proprietary `.ACD`, `.L5X`, `.L5K`, or PDF artifacts; canonical regression fixtures belong under `tests/acd/`.
- `src/sdk_interface/` is gated off by default. Do not expand SDK scope silently when an offline `src/acd/` path is the intended behavior.

## Special cases

**Multiple issues touched by one session** — name all governing issues in the session-start comment and use a `Refs` line for each in commits.

**Exploratory or diagnostic session** — skip this skill only when no change is planned. If investigation reveals a required code, test, skill, or configuration change, complete this workflow before editing.

**Session end** — report the outcome on each governing issue. Do not close issues from this skill unless the user explicitly requests it or the repository’s close-out workflow requires it.
