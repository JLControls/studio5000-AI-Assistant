---
name: status-sync
description: Use when landing a completed change, preparing a commit, or being asked to ship, land, wrap up, or close out work in JLControls/studio5000-AI-Assistant.
---

# Status sync — keep repository truth with changes

Run this checklist before declaring a change landed. In this repository, project truth lives in `AGENTS.md`, `docs/`, tests, generated-output conventions, and GitHub Issues; there is no `ROADMAP.md` or `CLAUDE.md` contract to maintain.

The unit of done is the implementation plus the tests and repository-documentation deltas it implies.

## Checklist

Fill every item. Write `n/a — <reason>` when an item does not apply.

1. **GitHub issue.** Identify the governing issue and comment with the result, evidence, and remaining limitations:

   ```powershell
   $repo = "JLControls/studio5000-AI-Assistant"
   gh issue comment NNN --repo $repo --body "<measured outcome, validation, and limitations>"
   ```

   Use the existing `type:bug`, `type:feature`, `severity:*`, and `area:*` labels; repository workflow, documentation, skills, and hooks normally use `area:ai_assistant`. Close an issue only when the work fully resolves it:

   ```powershell
   gh issue close NNN --repo $repo --reason completed
   ```

2. **Defects.** File new defects as `type:bug` with the applicable `severity:*` and `area:*` labels. Keep the issue body as the permanent reproduction record; add comments for later findings instead of erasing history.

3. **Superseded content.** If the change disproves or replaces a statement in `README.md`, `AGENTS.md`, `docs/`, a design note, or a test expectation, annotate or update it in the same change. Never silently leave stale guidance or delete an important decision.

4. **Repository guidance.** Update `AGENTS.md` only when a binding architecture, command, safety rule, or repository convention changed. Put user-facing workflows and design detail in the appropriate `docs/` file.

5. **Memory boundary.** Do not edit the user's private or auto-memory files from this repository workflow. Record durable project rules in `AGENTS.md` or `docs/`; create a follow-up issue for larger documentation work.

6. **File placement.** Keep new repository-relative paths at or below 150 characters for Windows worktree compatibility. Skills belong under `.agents/skills/<name>/`; Claude hook scripts belong under `.claude/hooks/`.

7. **MCP surface.** If the change adds or alters an agent-facing tool, update the registration and `inputSchema` in `src/mcp_server/studio5000_mcp_server.py`, the relevant integration adapter, and focused tests. Run the MCP smoke test.

8. **PLC artifacts.** Do not commit proprietary `.ACD`, `.L5X`, `.L5K`, or PDF artifacts. Keep canonical regression fixtures under `tests/acd/`, preserve native outputs as authoritative, and require Studio 5000 engineering review/validation before deployment.

9. **Skill and hook changes.** Validate each skill with the repository venv:

   ```powershell
   venv/Scripts/python.exe C:/Users/Sam.Black/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/<skill-name>
   ```

   Run `bash -n .claude/hooks/<hook>` when Bash is available, and perform a bounded smoke test for behavior changes.

## Commit and landing discipline

Before staging, inspect the current state:

```powershell
git status --short --branch
git diff --stat
git branch --show-current
```

Stage only files changed by this session. Never use a blanket `git add -A` or `git add .` when unrelated or concurrent work is present.

Use a concise imperative subject following the repository convention:

```text
<type>(<area>): <what changed> Refs #NNN
```

Use `Closes #NNN` only in the final commit that completely resolves the governing issue. GitHub links that commit to the issue and processes the automatic close when the commit reaches the repository's default branch. Use `Refs #NNN` for work that is not closing the issue. This checklist does not authorize pushing, creating a pull request, merging, or closing an issue beyond the user's stated request.

If the final commit contains `Closes #NNN`, continue directly into the `session-end` skill in the same turn. A mid-session commit containing only `Refs #NNN` does not end the session.

## Completion report

Report:

- governing issue and issue comment;
- files staged or intentionally left untouched;
- tests and validation commands with results;
- Studio 5000 review requirements for generated PLC logic;
- remaining risks, follow-up issues, or `n/a` checklist items.
