# Feature Roadmap

Planned work for the Studio 5000 AI Assistant, grouped by horizon. Hand-edited, in-tree.

**Legend**
- **ID:** `FEAT-NNN`, assigned sequentially, never reused.
- **Bucket:** `Now` (active / next up) · `Next` (queued) · `Later` (someday / lower priority).
- **Priority:** `High` · `Medium` · `Low`.
- **Resolves:** the [BUG](BUGS.md) IDs this feature would close, if any.
- SDK-interface (`src/sdk_interface`) work is out of scope — the live SDK is gated off by default and offline work targets the vendored `src/acd` parser.

## Summary

### Now
| ID | Priority | Summary | Resolves |
|----|----------|---------|----------|
| [FEAT-001](#feat-001--proper-rll-xml-generation) | High | Proper RLL XML generation (replace raw-text-in-CDATA output) | BUG-001 |
| [FEAT-002](#feat-002--analyze_comment_graph-convergence-tuning) | High | `analyze_comment_graph` convergence tuning & hardening | — |
| [FEAT-003](#feat-003--v38-l5x--acd-parity) | High | v38 L5X / ACD parity for the vendored offline parser/exporter | — |

### Next
| ID | Priority | Summary | Resolves |
|----|----------|---------|----------|
| [FEAT-004](#feat-004--structured-text-st--function-block-fbd-generation) | Medium | Structured Text (ST) + Function Block (FBD) generation | BUG-002 |
| [FEAT-005](#feat-005--advanced--static-validation) | Medium | Advanced / static validation & best-practices checking | — |
| [FEAT-009](#feat-009--direct-acd-comment-writer-patch_comments) | Medium | Direct ACD comment writer (`patch_comments`) — write descriptions into `Comments.Dat` | BUG-006 |
| [FEAT-010](#feat-010--acd-data-table-value-extraction) | Medium | ACD data-table value extraction — populate real tag/member values in the ACD→L5X export | — |

### Later
| ID | Priority | Summary | Resolves |
|----|----------|---------|----------|
| [FEAT-006](#feat-006--multiple-studio-5000-version-detection) | Low | Multiple Studio 5000 version detection & compatibility | — |
| [FEAT-007](#feat-007--factorytalk-view--rslinx-integration) | Low | Integration with FactoryTalk View / RSLinx | — |
| [FEAT-008](#feat-008--cloudweb-team-interface) | Low | Cloud/web interface for team collaboration | — |

## Details

### FEAT-001 — Proper RLL XML generation
- **Bucket:** Now · **Priority:** High · **Resolves:** BUG-001
- **Source:** README.md:993
- **Outcome:** Emit well-formed RLL XML for generated ladder logic instead of raw text in CDATA, so generated L5X imports into Studio 5000 without manual formatting fixes.

### FEAT-002 — `analyze_comment_graph` convergence tuning
- **Bucket:** Now · **Priority:** High · **Resolves:** —
- **Source:** src/comment_graph/, docs/superpowers/plans/2026-08-05-iterative-comment-analysis-plan.md
- **Outcome:** Tune and harden the iterative comment-analysis engine — convergence behavior, placeholder/seed filtering, and scheduler robustness — so proposals stabilize predictably on real projects.

### FEAT-003 — v38 L5X / ACD parity
- **Bucket:** Now · **Priority:** High · **Resolves:** —
- **Source:** Recent commits (f7cd63b "PLC: add v38 offline ACD parity workflow")
- **Outcome:** Bring the vendored offline ACD parser/exporter to full parity with Studio 5000 v38 L5X semantics for round-trip fidelity.

### FEAT-004 — Structured Text (ST) + Function Block (FBD) generation
- **Bucket:** Next · **Priority:** Medium · **Resolves:** BUG-002
- **Source:** README.md:1007
- **Outcome:** Extend generation beyond ladder to ST and FBD, replacing the current "not implemented" placeholder path.

### FEAT-005 — Advanced / static validation
- **Bucket:** Next · **Priority:** Medium · **Resolves:** —
- **Source:** README.md:1010
- **Outcome:** Add static analysis and best-practices checking on top of the existing fast syntax/instruction validation.

### FEAT-009 — Direct ACD comment writer (`patch_comments`)
- **Bucket:** Next · **Priority:** Medium · **Resolves:** BUG-006
- **Source:** docs/acd_comment_writer_spec.md; src/acd/zip/write_dat.py (`patch_sbregion_dat` precedent); src/acd/record/comments.py (parse-only today)
- **Outcome:** Write tag/operand comment *descriptions* directly into `Comments.Dat` so `edit_acd=True` emits a modified ACD containing the documentation, not just the `Comment_Delta.CSV` import. Phased: (1) byte-identical round-trip test, (2) modify existing comment records, (3) append type-1 tag descriptions (bind by `Comps` object_id — lower risk), (4) append type-11 operand comments (internal `.!HEXREF` binding — needs Studio validation), (5) wire into `comment_pipeline.generate_deliverables`. Full format notes and validation gap in the spec doc.

### FEAT-010 — ACD data-table value extraction
- **Bucket:** Next · **Priority:** Medium · **Resolves:** —
- **Source:** `src/acd/l5x/elements.py` (`Tag.to_xml` lines ~500-513; zero-maps `_PRIMITIVE_L5K_ZERO` ~160-172 and `_PRIMITIVE_DECORATED_ZERO` ~190-203; `_data_table_instance` stored at ~436 but never used); `src/acd/record/sbregion.py` (keeps only `Rung NT`/`REGION NT`, `pass`es on other region types).
- **Problem:** The vendored ACD→L5X exporter **never reads tag data-table values** — it emits hardcoded type-default zeros for every tag value/member. The `data_table_instance` pointer is parsed but never dereferenced. Consequence: a converted L5X has all `DataValue`/`DataValueMember` values zeroed (e.g. every `SCPLim1` `InputMin/InputMax/ScaledMin/ScaledMax` = 0), so anything reading real values off a *converted* project (e.g. `extract_analog_scaling` / `generate_ignition_tags` in `src/ignition_exporter`) gets nothing. A **native** Studio 5000 L5X export preserves the values and works today; only the offline ACD-conversion path is affected.
- **Outcome:** Populate real tag/member values in the ACD→L5X export so converted projects match a native export. Phased: (1) reverse-engineer the ACD data-table value blob layout (diff a known ACD's values against its native L5X export, keyed by `data_table_instance`); (2) decode the blob into a `{data_table_instance → member values}` map during `ExportL5x` load; (3) thread the map through `TagBuilder` → `Tag.to_xml` → `_generate_decorated`/L5K render so each scalar/array/nested-UDT/built-in-struct value renders its real value with correct radix/endianness; (4) regression-guard with `tests/acd/`. Large (new parsing subsystem, not a minimal edit); until done, prefer a native L5X export whenever value fidelity matters.

### FEAT-006 — Multiple Studio 5000 version detection
- **Bucket:** Later · **Priority:** Low · **Resolves:** —
- **Source:** README.md:1013
- **Outcome:** Dynamically detect the installed Studio 5000 version and adapt documentation roots / L5X targets for compatibility across major revisions.

### FEAT-007 — FactoryTalk View / RSLinx integration
- **Bucket:** Later · **Priority:** Low · **Resolves:** —
- **Source:** README.md:1014
- **Outcome:** Extend beyond Logix Designer to related Rockwell tools (FactoryTalk View, RSLinx) for broader system context.

### FEAT-008 — Cloud/web team interface
- **Bucket:** Later · **Priority:** Low · **Resolves:** —
- **Source:** README.md:1015
- **Outcome:** Provide a web-based interface for team collaboration over the assistant's capabilities.
