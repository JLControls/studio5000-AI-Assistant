---
name: session-end
description: Use when the user says wrap up, close session, end session, close out this task, or when a commit containing `Closes #NNN` has just landed in JLControls/studio5000-AI-Assistant.
---

# Session end

Use this as the close-side bookend to `session-start`. Run the four phases in order and present one consolidated report. `status-sync` remains the per-commit checklist; `session-end` adds the once-per-session ship, knowledge, review, and handoff work.

## Automatic trigger

If the commit just landed contains `Closes #NNN`, continue directly into this skill in the same turn. Do not wait for another user message. The `.claude/hooks/session-end-guard.sh` hook is only a backstop; the closing commit is the signal.

## Phase 1 — Ship and verify

1. Inspect the current state:

   ```powershell
   git status --short --branch
   git branch --show-current
   git log -1 --oneline
   ```

2. Run the `status-sync` checklist. Reconcile issue comments, repository documentation, generated-output rules, and validation requirements before landing.

3. Stage only files changed by this session. Never use `git add -A` or `git add .` when unrelated or concurrent work is present. Review each staged path.

4. Run the relevant verification before committing:

   - Python changes: `venv/Scripts/python.exe -m pytest` or the focused test selection.
   - MCP server changes: `venv/Scripts/python.exe src/mcp_server/studio5000_mcp_server.py --test`.
   - Skill changes: the repository venv plus `quick_validate.py` for every changed skill.
   - Hook changes: `bash -n .claude/hooks/session-end-guard.sh` and bounded fixture tests for the `Closes #NNN` and marker cases.
   - Generated PLC logic: require engineering review and Studio 5000 validation; do not treat offline checks as deployment approval.

5. Commit in the current repository workflow with a concise imperative subject:

   ```text
   <type>(<area>): <what changed> Refs #NNN
   ```

   Use `Closes #NNN` only when the governing issue is fully resolved. GitHub links that commit to the issue and processes the automatic close when the commit reaches the repository's default branch. Do not push, create/merge a pull request, or change branches unless the user explicitly asks.

6. Check file placement and path lengths. Skills belong under `.agents/skills/`; Claude hooks belong under `.claude/hooks/`; new repository-relative paths must stay at or below 150 characters.

7. If this session stopped or repointed an owner-facing service or process, restore its prior state and verify it. Do not kill a process owned by another active session.

8. Mark the session's plan tasks complete, and identify stale or orphaned work for a follow-up issue instead of silently dropping it.

## Phase 2 — Record durable knowledge

Place each useful finding in the smallest durable home:

- `AGENTS.md` — permanent repository rules, architecture, commands, and safety constraints.
- `docs/` — user-facing workflows, design decisions, measured results, and troubleshooting.
- GitHub Issue — defects, follow-up work, and unresolved risks.
- Private or auto-memory — do not edit from this repository workflow unless the user explicitly requests a memory update.

Do not add a second copy of information that should be referenced from an existing document.

## Phase 3 — Review and improve

Review this session for skill gaps, repeated friction, missing project knowledge, or useful automation. For a routine session with no actionable finding, report `Nothing to improve`.

Apply only improvements that are explicitly in this task's scope. For a material follow-up, create or update a GitHub Issue rather than changing unrelated code, skills, hooks, or `AGENTS.md` during close-out.

Report findings in two groups:

1. **Applied** — changes made and validated in this session.
2. **No action** — useful observations deferred, with their proposed issue or documentation home.

## Phase 4 — Handoff

Provide a concise forward-looking report:

**Next development steps**

- logical follow-up tasks, with the governing issue;
- scope and blockers;
- architecture decisions that constrain or unlock the next task.

**Owner verification needed**

- Studio 5000 validation or engineering review for generated PLC logic;
- physical, environment, or UI checks that cannot be verified here;
- assumptions that remain unverified.

**Risks and opportunities**

- edge cases, regression risks, and performance cliffs;
- worthwhile follow-up improvements;
- the GitHub Issue or document where each should persist.

If none apply, say `No forward-looking items`.

## Final idempotency marker

As the final action, record the current `HEAD` so the Stop-hook does not re-prompt for the same commit:

```powershell
$gitDir = (git rev-parse --git-dir).Trim()
$head = (git rev-parse HEAD).Trim()
Set-Content -LiteralPath (Join-Path $gitDir "session-end-done") -Value $head -NoNewline
```

For a Bash hook environment, the equivalent is:

```bash
git rev-parse HEAD > "$(git rev-parse --git-dir)/session-end-done"
```

The marker is local `.git/` state and must never be committed.
