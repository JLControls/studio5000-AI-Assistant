# Roadmap — unimplemented plans and specs

Status date: 2026-09-18, measured against `main` at the docs-consolidation commit
plus the Phase 1 item 1 implementation in this working tree.
This file is the single source of truth for *what is left*. The plan and spec
documents describe *how*; this file says *whether* and *in what order*.

Verdict scale: **Done** (moved to `completed/`), **Mostly done** (>=80%),
**Partial**, **Not started**, **Deferred** (conflicts with committed behaviour;
needs a decision before work starts).

Test baseline at the status date: `.venv/bin/python -m pytest` = 423 passed,
3 skipped (the optional Stage 1 parity fixtures are not present);
`.venv/bin/python src/mcp_server/studio5000_mcp_server.py --test` completes
successfully, with expected warnings for the empty local instruction index and
the read-only Hugging Face cache path. The shell `python` is 3.13.5 and is not
the project validation environment.

---

## 1. Status board

| ID | Document | Verdict | % | Governing issue | Blocking / blocked by |
| :--- | :--- | :--- | :---: | :--- | :--- |
| PLAN-01 | Deterministic AST cross-reference | Mostly done | 80 | #26, #12 | Blocks 05, 07, 13 |
| PLAN-02 | ACD `patch_rungs` @HEX@ substitution | Partial | 50 | #34 | Blocks 03, 06 |
| PLAN-03 | Direct ACD comment writer | **Deferred** | 0 | #22, #6 | Needs golden Type-1 record bytes; code and tests currently assert *unsupported* |
| PLAN-04 | ACD data-table value extraction | Not started | 0 | #23 | Needs golden Comps.Dat fixture; blocks 08 accuracy |
| PLAN-05 | PLC static-analysis linter | Not started | 0 | #18 | Needs PLAN-01 close-out; shared semantics table landed |
| PLAN-06 | Safe modification staging / diff | Not started | 0 | — | Needs 02; supersedes direct write in `smart_insert_logic` |
| SPEC-07 | Equipment liveness classifier | Not started | 0 | #27 | Needs 01, JSR walker from 05 |
| PLAN-08 | SCADA Ignition coverage, scaling, report | Partial | 45 | #10, #24, #25 | Task 1+2 done; 3/4 open; better with 04 |
| PLAN-09 | Secure cache and deserialization | Mostly done | 80 | #36 | Fingerprint validity, bandit in CI (10) |
| PLAN-10 | CI and build infrastructure | Partial | 25 | #35 | Baseline job exists |
| PLAN-11 | Core bug fixes and MCP reliability | Partial | 35 | #37, #38, #39, #5 | Independent, small |
| SPEC-12 | Documentation versioning and drawings | Not started | 0 | #19 | Independent, P2 |
| SPEC-13 | Interface audit engine | Not started (spec only) | 0 | — | Must be rebased on 01, 05, 07; no plan yet |

Delivered since the 2026-08-21 review and now in `completed/`:
vendored ACD parser, ACD/L5X v38 fidelity, iterative comment graph, human
Ignition naming engine (#29), bug-tracker design (superseded by GitHub Issues).

---

## 2. Cross-cutting item that comes first

**One shared instruction-semantics table — delivered in this change.** Operand
read/write roles now come from `src/plc_instruction_semantics.py`, consumed by:

- `src/l5x_analyzer/tag_cross_reference.py`
- `src/l5x_analyzer/write_analyzer.py`
- `src/comment_graph/edges.py`
- `src/tag_analyzer/comment_pipeline.py`
- `src/verification/sdk_verifier.py` and `src/comment_graph/builder.py`

Plans 01, 05, 07, 08 and 13 all consume this. The shared table is the review
gate for later work; it does not close PLAN-01. `sdk_verifier.py` is now the
single verifier implementation and compatibility import path.

---

## 3. Phased order

Dependency-ordered. Each phase leaves `main` releasable.

### Phase 1 — Foundation (small, independent, unblocks everything)

1. **Shared semantics table — Done (2026-09-18).** `src/plc_instruction_semantics.py`
   now owns `OperandRole`, read/write/control operand selectors, the known
   instruction vocabulary, and `is_destructive`. Cross-reference, write
   detection, comment-graph edges, rung-structure parsing, and verifier
   vocabulary consume it; `COP` and timer/control writes are covered by tests.
   The byte-identical `sdk_verifier_clean.py` duplicate was removed and
   `sdk_verifier.py` remains the compatibility entry point. The remaining
   PLAN-01 work is API completeness, richer operand coverage, ACD provenance,
   and synthetic fixture evidence.
2. **PLAN-11 remainder.** Remaining fixes, each with a test in a new
   `tests/test_core_bugfixes.py`:
   - BUG-04: list available indexed projects in the wrong-project error.
   - BUG-06: `file=sys.stderr` on the five `__main__` print runners; add a
     subprocess JSON-RPC framing test.
   - BUG-07: accept `target_program` alias in `generate_routine_export` and the
     `create_l5x_routine` schema.
   - BUG-08: real seal-in branch for start/stop logic in `code_assistant.py`.
   - Remove fictitious `PRODUCE`/`CONSUME` mappings.
   - Python 3.12 guard inside `main()`.
   - Fix the `INPUT_ONLY` false warning in the verifier using the shared table.
3. **PLAN-10 remainder.** Add `--test` smoke step to the Linux job, a
   lint-and-security job (flake8 E9/F63/F7/F82 blocking, bandit advisory),
   `.flake8`, `.bandit.yaml`, README badge. Measure runtime before adding a
   Windows job.
4. **PLAN-09 remainder.** Cache-validity fingerprint (source hash + model name +
   schema version), reset in-memory integrations after `clear_vector_cache`,
   bandit wired via PLAN-10. Then close #36.

### Phase 2 — Deterministic analysis

5. **PLAN-01 close-out.** `match_sub_elements` flag through engine, handler and
   schema; `.acd` ingestion with conversion provenance; ST function-call rows;
   synthetic `cross_ref_sample.L5X` fixture and test; delete the dead
   `L5XVectorDB.find_related_components`. Close #26 and #12.
6. **PLAN-05 linter.** `src/verification/plc_linter.py`, six rules in the
   plan's order, `lint_plc_logic` tool. Rule 5 (JSR reachability) becomes a
   shared call-graph walker that SPEC-07 reuses. Close #18.
7. **SPEC-07 liveness.** Write the plan first (none exists). Module walker,
   I/O reference signal via `find_tag_references`, JSR walker from step 6,
   decision matrix with provenance, `audit_equipment_liveness` tool. Close #27.

### Phase 3 — ACD byte engine

8. **PLAN-02 hardening.** `TagNotFoundError` with strict/advisory modes,
   gzip-state round trip in `patch_sbregion_dat`, malformed-syntax pre-check,
   `tests/acd/test_patch_rungs_hex.py` with the seven plan cases. Close #34.
9. **PLAN-04 values.** Needs a tracked golden Comps.Dat fixture first; the
   record-type hypothesis in the plan is unproven. Then `TagValueDecoder`,
   replace the five zero-emitting sites in `acd/l5x/elements.py`, typed
   "unavailable" provenance, Kemco e2e assertions. Close #23. Revisit the
   Ignition "distrust all-zero" heuristic afterwards.
10. **PLAN-03 decision point.** The tree now documents direct ACD comment
    writing as unsupported and a test asserts that. Either (a) validate the
    Type-1 record layout against golden bytes and execute the plan, reversing
    the pipeline gate and the three MCP descriptions, or (b) close #22 and
    #6 as "CSV import is the supported path" and delete the plan. Do not
    start (a) until PLAN-02 gzip handling and `set_fileinfo_key` integrity
    are in place.

### Phase 4 — Safe mutation

11. **PLAN-06 staging engine.** `staging_diff_engine.py`, three tools
    (`stage_insert_logic`, `apply_staged_change`, `discard_staged_change`),
    SHA-256 binding, atomic replace, collision-safe backups. Then route
    `smart_insert_logic` through it or fail closed. The plan's stricter
    contract (no `create_backup` flag, both digests required) wins over the
    spec's.

### Phase 5 — SCADA export and reporting

12. **PLAN-08 tasks 3–6.** `io_coverage.py` with physical-channel
    denominators, `html_reporter.py` with zero-CDN escaped output,
    `audit_scada_io_coverage` and `generate_scada_export_report` tools,
    schema tests. Pick one parameter naming (`l5x_file_path` from the plan).
    Decide whether unscaled points get a `documentation` note in the payload
    or stay manifest-only. Close #10, #24, #25.

### Phase 6 — Interface audit engine (SPEC-13)

13. **Reconcile before building.** SPEC-13 was written without reference to
    `tag_cross_reference.py` and `l5x_fact_accessor.py`, which already cover
    most of its `find_tag_writers` and value-provenance sections. Its data-
    movement checks are PLAN-05 lint rules; its interface-tag verdicts are
    SPEC-07's classifier. Rewrite §2 of the spec against the current tree,
    then write a checkbox plan for Phases 0–2 only:
    - schema registry refactor (`add_tool(..., input_schema=)`) with a test
      that every tool has a schema;
    - `find_tag_writers` as a write-filtered, bit-resolving view over
      `find_tag_references`;
    - UDT byte-layout model and COP overlap/overrun check, delivered as
      PLAN-05 rules.
    Defer alarm map, MSG audit, provenance, reference-doc ingestion and
    historian round-trip until those land. Public synthetic fixtures only;
    the Perry/Vemac files stay out of acceptance criteria.

### Backlog (P2, no dependency)

14. **SPEC-12.** `studio_version`/`controller_family` metadata on instruction
    chunks and `search_instructions` filters; span stitching in
    `pdf_parser.py`; remove the stale "Vision AI" README claims. Close #19.

---

## 4. Duplication removed in this consolidation

- `docs/acd_comment_writer_spec.md` deleted; SPEC-03 is canonical.
- PLAN-08 Task 2 marked as delivered by the naming-engine plan; do not
  re-implement.
- `2026-09-17-interface-audit-engine.md` moved from `plans/` to
  `specs/13-...` because it is a proposal with no checkbox tasks.
- Bug-tracker design archived; GitHub Issues on `JLControls/studio5000-AI-Assistant`
  are the tracker. Note `gh` defaults to the `rivie13` fork here (issue #40).
- Shared instruction semantics consolidated in `src/plc_instruction_semantics.py`;
  the byte-identical verifier duplicate was deleted.

## 5. Known duplication still in the tree

- `SharedCacheManager.is_cache_valid` and `SecureVectorCache.is_cache_valid`
  are two age-only validators.
- `@HEX@` token regex in `acd/record/sbregion.py`, `acd/record/comments.py`
  and `acd/zip/write_dat.py`.
- Two parity gates with different env-var conventions:
  `tests/acd/test_stage1_parity.py` (`PLC_DOCGEN_TEST_*`) and
  `tests/test_acd_l5x_fidelity.py` (`THAWROOM_*`).

## 6. Open hardening carried over from completed work

- Comment graph: `INSTRUCTION_DOC` enrichment tier is declared but never
  used; no cancellation path guaranteeing "no deliverables on cancel". (#15)
- v38 fidelity: document the parity command in AGENTS.md and record one
  parity-loss report from the thaw-room fixture. (#16)
