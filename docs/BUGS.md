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
| [BUG-007](#bug-007--over-export-of-non-relevant-internal-tags) | High | Fixed | ignition_exporter | Generator emits non-operator internal tags without applying a relevance discriminator |
| [BUG-008](#bug-008--opc-tags-point-to-complex-udt-struct-roots-instead-of-atomic-members) | High | Fixed | ignition_exporter | Tag builder creates AtomicTag items pointing directly at UDT struct roots (e.g. `Com_HWT1`) instead of atomic members |

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

### BUG-007 — Over-export of non-relevant internal tags (missing relevance discriminator)
- **Area:** ignition_exporter
- **Severity:** High
- **Status:** Fixed
- **Source:** `src/ignition_exporter/tag_curation.py`, `src/ignition_exporter/ignition_mcp_integration.py`
- **Description:** The tag curation and export generator emits far too many tags (over 1,100 tags) when generating an export without aggressive filtering. While the write-detection engine prunes unwritten internal tags, it lacks a strict relevance discriminator to distinguish between primary operator-facing process metrics (analog PVs, active interlock alarms, operator setpoints, status bits) and intermediate calculation scratch bits, drive-comms registers, or internal state timers.
- **Trigger:** Calling `generate_ignition_tags` or `list_ignition_tag_candidates` on any Logix project with large UDT structures or internal logic tags.
- **Workaround:** Pass an explicit curated `target_tags` list or `tag_overrides` specifying only key process metric tags.
- **Fix:** Added a shared *Balanced* relevance discriminator (`is_export_relevant` + `build_write_map` in `tag_curation.py`) used by **both** `list_ignition_tag_candidates` (discovery) and the curated default of `generate_ignition_tags`, so the recommended set and the written file agree. Only operator-facing (KEY) categories qualify; analog PVs / setpoints / field-I/O are always kept, while alarm / status / command bits are kept only with live evidence (written by logic, or a physical-field naming convention), pruning dead scratch bits. Verified on the Kemco project: curated default 505 tags vs `selection="all"` 1188. `selection="all"` remains the documented escape hatch.

### BUG-008 — OPC tags point to complex UDT struct roots instead of atomic members
- **Area:** ignition_exporter
- **Severity:** High
- **Status:** Fixed
- **Source:** `src/ignition_exporter/ignition_tag_builder.py`, `src/ignition_exporter/aoi_structure_parser.py`
- **Description:** When processing complex User-Defined Data Types (UDTs) or Add-On Instruction (AOI) structures (e.g. `Com_HWT1` of type `TData1` or `Com_CW` of type `FData1`), `_collect_export_items` creates an `AtomicTag` whose `opcItemPath` points directly to the struct root (`ns=1;s=[Device]Com_HWT1`). Ignition's OPC UA server cannot read complex Logix UDT structures as atomic scalar OPC items, resulting in SCADA import errors or `Bad_TypeMismatch` / `Bad_NotReadable` runtime OPC errors. Complex UDT root tags must be pruned from export, while only their atomic scalar sub-members (`Com_HWT1.Temp`, `Com_CW.Flow`, `Com_CW.Tot`) are mapped as scalar AtomicTags.
- **Trigger:** Generating Ignition tags for a project containing UDT structure tags like `TData1`, `FData1`, `Btu1`, or `SCP`.
- **Workaround:** Manually filter out root struct tag entries from `ignitionTags.json` and map atomic child members explicitly.
- **Fix:** Wired the existing struct expander (`aoi_structure_parser.py`) into the **generation** path (it was previously only used by discovery). `_collect_export_items` now prunes expandable struct roots and emits their atomic members with correct per-member Ignition types (`_ExportItem.ign_dtype`/`eng_unit`, so Boolean/Int members are no longer forced to `Float4`); bare struct roots passed via `tag_overrides` auto-expand into members inheriting the friendly name/folder; and `verify_tree_against_l5x` now raises on any bare expandable struct root (not just COUNTER/TIMER). Parser lookups are case-insensitive. Verified on the Kemco project (141 expandable structs across SCP/HrCtr1/Btu1/FData1/TData1/…): zero struct-root leaks in both curated and `all` output.

