# Bug Tracker

Known defects in the Studio 5000 AI Assistant. Lightweight, in-tree, hand-edited.

**Legend**
- **ID:** `BUG-NNN`, assigned sequentially, never reused.
- **Severity:** `Critical` (data loss / unusable) · `High` (core feature broken or produces bad output) · `Medium` (feature partial / degraded) · `Low` (minor / environmental).
- **Status:** `Open` · `In Progress` · `Fixed` · `Won't Fix`.
- **Source:** `file:line` citation for where the issue is grounded.
- SDK-interface (`src/sdk_interface`) issues are out of scope — the live SDK is gated off by default and offline work targets the vendored `src/acd` parser.

## Summary

| ID | Severity | Status | Area | Summary |
|----|----------|--------|------|---------|
| [BUG-001](#bug-001--generated-l5x-emits-raw-text-in-cdata-not-rll-xml) | High | Open | code_generator | Generated L5X emits raw ladder text in CDATA rather than proper RLL XML |
| [BUG-002](#bug-002--structured-text-generation-not-implemented) | Medium | Open | ai_assistant | Structured Text (ST) generation not implemented for patterns |
| [BUG-003](#bug-003--enhanced-generator-emits-todo-placeholder-logic) | Medium | Open | ai_assistant | Enhanced ladder generator emits a `// TODO` placeholder for unmatched cases |
| [BUG-004](#bug-004--complex-l5k-structured-encoding-not-implemented) | Low | Open | acd | Complex structured L5K encoding not yet implemented in the vendored exporter |
| [BUG-005](#bug-005--python-312-required-env-may-resolve-to-314) | Low | Open | env/tests | Hard Python 3.12 requirement; env may resolve `python` to 3.14 and break tests |
| [BUG-006](#bug-006--edit_acd-silently-writes-no-comment-descriptions) | Medium | Open | acd | `edit_acd=True` silently writes no comment descriptions (only rung text); comment-only decisions yield an unchanged ACD |

## Details

### BUG-001 — Generated L5X emits raw text in CDATA, not RLL XML
- **Area:** code_generator
- **Severity:** High
- **Status:** Open
- **Source:** README.md:84, README.md:993
- **Description:** L5X project/routine generation outputs raw ladder logic text wrapped in CDATA instead of proper RLL XML structure. Files follow the Studio 5000 schema loosely but frequently need manual formatting fixes before they import cleanly.
- **Trigger:** `create_l5x_project` / `create_l5x_routine` with any non-trivial ladder logic.
- **Workaround:** Use generated L5X as a template/scaffold, then correct RLL formatting manually in Studio 5000. Resolved by [FEAT-001](ROADMAP.md#feat-001--proper-rll-xml-generation).

### BUG-002 — Structured Text generation not implemented
- **Area:** ai_assistant
- **Severity:** Medium
- **Status:** Open
- **Source:** src/ai_assistant/code_assistant.py:338
- **Description:** For patterns that would target Structured Text, the assistant returns the placeholder `// ST generation not implemented for this pattern` rather than real logic.
- **Trigger:** Requesting ST output for a pattern the generator doesn't cover.
- **Workaround:** Author ST manually; only ladder (RLL) generation is supported. Tracked toward [FEAT-004](ROADMAP.md#feat-004--structured-text-st--function-block-fbd-generation).

### BUG-003 — Enhanced generator emits TODO placeholder logic
- **Area:** ai_assistant
- **Severity:** Medium
- **Status:** Open
- **Source:** src/ai_assistant/enhanced_ladder_generator.py:1149
- **Description:** When the enhanced ladder generator hits a case it has no specific handler for, it emits `// TODO: Implement specific logic based on requirements` instead of failing or producing usable logic.
- **Trigger:** A specification that doesn't match a recognized pattern.
- **Workaround:** Review generated output for TODO markers before use; fill in the logic manually.

### BUG-004 — Complex L5K structured encoding not implemented
- **Area:** acd
- **Severity:** Low
- **Status:** Open
- **Source:** src/acd/l5x/elements.py:159
- **Description:** Certain tags/elements require complex structured L5K encoding that the vendored ACD→L5X exporter does not yet implement, so they are omitted from export.
- **Trigger:** Converting an ACD containing structured elements that need L5K encoding.
- **Workaround:** None; affected elements are excluded from the exported L5X.

### BUG-005 — Python 3.12 required; env may resolve to 3.14
- **Area:** env/tests
- **Severity:** Low
- **Status:** Open
- **Source:** CLAUDE.md, requirements.txt
- **Description:** The project pins to Python 3.12 (torch / sentence-transformers versions). The local environment may resolve `python` to a 3.14 interpreter, under which the test suite does not run correctly.
- **Trigger:** Running `python -m pytest` with the wrong interpreter on PATH.
- **Workaround:** Explicitly invoke the 3.12 interpreter / venv before running tests.

### BUG-006 — `edit_acd` silently writes no comment descriptions
- **Area:** acd
- **Severity:** Medium
- **Status:** Open
- **Source:** src/tag_analyzer/comment_pipeline.py (`generate_deliverables` ACD-edit branch); src/acd/record/comments.py (parse-only)
- **Description:** `generate_deliverables(edit_acd=True)` only patches rung **text** (decisions with `PROPOSED_RUNG_TEXT` via `patch_rungs`). Comment/description decisions are ignored by the ACD-edit path because `acd/record/comments.py` is parse-only — there is no comment writer. A comment-only run therefore produces an `_updated.ACD` that is effectively unchanged, which reads as success but silently drops the documentation.
- **Trigger:** `edit_acd=True` with decisions carrying `PROPOSED_DESCRIPTION` but no `PROPOSED_RUNG_TEXT`.
- **Workaround:** Use the `Comment_Delta.CSV` import in Studio 5000 (correct bindings, no corruption risk). A real fix is the direct comment writer — [FEAT-009](ROADMAP.md#feat-009--direct-acd-comment-writer-patch_comments) — spec in [acd_comment_writer_spec.md](acd_comment_writer_spec.md).
