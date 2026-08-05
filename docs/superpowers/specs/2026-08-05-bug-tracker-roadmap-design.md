# Bug Tracker & Feature Roadmap — Design

**Date:** 2026-08-05
**Status:** Approved (pending spec review)

## Purpose

Give this repo a lightweight, in-tree place to track known defects and planned work.
No infrastructure, no scripts — plain markdown that is diffable, greppable, and lives next to
the code. Seed it with the project's *real* known issues and roadmap, each entry citing its
source so nothing is unverifiable.

## Scope

**In:** four markdown files (two tracking docs + two GitHub issue templates), seeded with 5 bugs
and 8 roadmap features mined from the README and source.

**Out (YAGNI):**
- Any automation syncing docs ↔ GitHub Issues.
- Status dashboards, scripts, or generators.
- **Anything depending on the live Studio 5000 SDK** (`src/sdk_interface`). The SDK is gated off by
  default (`STUDIO5000_SDK_ENABLED=false`) and offline work targets the vendored `src/acd` parser,
  so SDK-dependent defects/features are explicitly excluded.

## Deliverables

```
docs/BUGS.md
docs/ROADMAP.md
.github/ISSUE_TEMPLATE/bug.md
.github/ISSUE_TEMPLATE/feature.md
```

## Format Conventions

Both tracking docs share the same shape:

1. **Header** — one-paragraph purpose + a legend (ID scheme, severity/priority, status values).
2. **Summary table** — one row per item for scanning.
3. **Detail sections** — one `###` anchor per ID with description, area, source citation, and
   (for bugs) repro/workaround.

- **Bug IDs:** `BUG-NNN`. **Severity:** `Critical | High | Medium | Low`.
  **Status:** `Open | In Progress | Fixed | Won't Fix`.
- **Feature IDs:** `FEAT-NNN`. Grouped **Now / Next / Later**. Each feature notes the BUG(s) it
  resolves where applicable.
- **Source citations** use `README.md:NNN` or `src/…:NNN` form.

New items get the next free integer ID; IDs are never reused.

## Seeded Content — Bugs (`docs/BUGS.md`)

| ID | Severity | Status | Area | Summary |
|----|----------|--------|------|---------|
| BUG-001 | High | Open | code_generator | Generated L5X emits raw ladder text inside CDATA rather than proper RLL XML; files need manual fixes before import (README.md:84, 993) |
| BUG-002 | Medium | Open | ai_assistant | Structured Text (ST) generation is not implemented for patterns; returns a placeholder comment (src/ai_assistant/code_assistant.py:338) |
| BUG-003 | Medium | Open | ai_assistant | Enhanced ladder generator emits `// TODO: Implement specific logic based on requirements` for unmatched cases (src/ai_assistant/enhanced_ladder_generator.py:1149) |
| BUG-004 | Low | Open | acd | Complex structured L5K encoding is not yet implemented in the vendored ACD L5X exporter (src/acd/l5x/elements.py:159) |
| BUG-005 | Low | Open | env/tests | Hard Python 3.12 requirement; the environment may resolve `python` to 3.14, which breaks the test suite (CLAUDE.md, requirements.txt) |

Each row expands to a `### BUG-NNN — <summary>` section with: Area, Severity, Status, Source,
Description, Repro/Trigger, and Workaround (if any).

## Seeded Content — Roadmap (`docs/ROADMAP.md`)

**Now (active / next up)**

| ID | Priority | Summary | Resolves |
|----|----------|---------|----------|
| FEAT-001 | High | Proper RLL XML generation (replace raw-text-in-CDATA output) | BUG-001 |
| FEAT-002 | High | `analyze_comment_graph` convergence tuning & hardening | — |
| FEAT-003 | High | v38 L5X / ACD parity for the vendored offline parser/exporter | — |

**Next**

| ID | Priority | Summary | Resolves |
|----|----------|---------|----------|
| FEAT-004 | Medium | Structured Text (ST) + Function Block (FBD) generation (README.md:1007) | BUG-002 |
| FEAT-005 | Medium | Advanced/static validation & best-practices checking (README.md:1010) | — |

**Later**

| ID | Priority | Summary | Resolves |
|----|----------|---------|----------|
| FEAT-006 | Low | Multiple Studio 5000 version detection & compatibility (README.md:1013) | — |
| FEAT-007 | Low | Integration with FactoryTalk View / RSLinx (README.md:1014) | — |
| FEAT-008 | Low | Cloud/web interface for team collaboration (README.md:1015) | — |

Each row expands to a `### FEAT-NNN — <summary>` section with: Priority, Bucket, Source, and a
short description of the desired outcome.

## Issue Templates

`.github/ISSUE_TEMPLATE/bug.md` and `feature.md` carry front matter (`name`, `about`, `labels`,
`title` prefix) and a body whose fields mirror the doc sections, so a filed issue drops cleanly
into `BUGS.md` / `ROADMAP.md`:

- **bug.md** — Summary, Area, Severity, Source (file:line if known), Repro/Trigger, Expected,
  Workaround.
- **feature.md** — Summary, Bucket (Now/Next/Later), Priority, Resolves (BUG IDs), Desired outcome,
  Source.

## Testing / Validation

No code, so no automated tests. Validation is manual: confirm all four files render as valid
markdown, every table row has a matching detail anchor, and every cited `file:line` reference
resolves in the current tree.
