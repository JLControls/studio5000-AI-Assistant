# Plan: `analyze_comment_graph` — Iterative PLC Comment Analysis

## Context

Today the PLC comment pipeline splits context extraction from decision generation: `get_tag_reasoning_context` reads a tag and its rungs **once**, `generate_comment_deliverables` serializes caller-supplied decisions, and `manage_comment_memory` records routine hashes with no dependency invalidation. The calling agent (Claude) has to manually re-issue one-shot context queries to propagate a newly-learned fact, and nothing requeues upstream producers.

The thaw-room fixture shows the failure mode:

```text
MOV(ENETBRIDGE_5069:1:I.Ch00.Data, N18[1])
ADD(N18[1], 1, N101[18])
```

`N101[18]` carries a native operand comment ("calibrated temperature, Thawing Room 1 RTD A"). That fact should sharpen the interpretation of `N18[1]` and everything downstream — but the current workflow never requeues `N18`, its rung, or its consumers. The current dependency extractor (`l5x_chunk.extract_tags_from_ladder_logic`) is destination-only regex and exposes no read/write graph.

This plan adds a server-side MCP tool, **`analyze_comment_graph`**, that owns the full lifecycle: build a typed dependency graph, seed facts from evidence, propagate to a deterministic fixed point (with predecessor invalidation, SCC/cycle handling, and bounded parallel execution), and emit deliverables only from the converged state. Design spec: `docs/superpowers/specs/2026-08-05-iterative-comment-analysis-design.md`.

**Key decisions (from the user):**
1. **Full spec**, sequenced into the 7 review checkpoints below.
2. **Deterministic-first worker.** Derive everything possible from evidence without discarding information. On *genuine* ambiguity the worker must **not fabricate** — it emits an `AssistanceRequest` naming the entity, the ambiguity, evidence gathered, and a **suggested model level** (haiku/sonnet/opus). An LLM/agent callback worker is injectable later; the default path uses no LLM.
3. **Fixtures:** the real, already-gitignored files `tests/acd/ModernTHAWROOM021722.{ACD,L5X}` drive the end-to-end regression (native `.L5X` authoritative; ACD path via the existing converter). Tiny synthetic L5X strings drive fast unit tests.

## Approach

New pure-library package `src/comment_graph/` (no MCP/asyncio coupling except the executor), wired into the existing hand-rolled JSON-RPC server. Reuse existing parsers/renderers wherever they exist — the graph/fact engine is the only genuinely new logic.

### Reuse anchors (do not reinvent)
- **Instruction/operand parsing:** `LadderParser`, `LadderInstruction`, `_split_operands` — `src/ladder_renderer/ladder_to_dot.py` (`INSTRUCTION_TYPES` :123, `parse_rung` :207, `_split_operands` :333, base-tag rule in `get_primary_tag` :87).
- **Read/write direction rules** to lift into the edge extractor: `ModelGenerator._operation` (:1139 — MOV `ops0→ops1`; ADD/SUB/MUL/DIV `ops0,1→ops2`; COP `ops0→ops1[ops2]`; CPT `ops0:=ops1`; compares read-only) and destructive-output set `ModelGenerator._OUTPUT_TYPES` (:1027 — COIL/LATCH/UNLATCH, TIMER, COUNTER, RESET, AOI).
- **Operand-comment/metadata seeding:** `inventory_l5x` — `src/l5x_analyzer/l5x_semantic_validation.py` (:52; `operand_comments` keyed `(tag, Operand)` :79, plus `rung_comments`, `modules`, `descriptions`).
- **ACD path:** `convert_acd_to_l5x(input, output, reference_path=None)` — `src/l5x_analyzer/acd_offline_convert.py` (:41; returns provenance `acd_source`/`inventory`/`note`/`validation`).
- **Deliverables + memory:** `PLCCommentPipeline` — `src/tag_analyzer/comment_pipeline.py`: `resolve_l5x_path` (:40), `parse_l5x_tree` (:69, strips BOM), `_process_tags_node` (:92, reads per-operand comments), `generate_deliverables` (:254 — CSV cp1252/CRLF/`$N`, 3 prefix lines, 7-col header; consumes **UPPERCASE** decision keys), `manage_incremental_memory` (:1084 — SHA-256 per `program/routine`, memory JSON `{project, routines, tags}`).
- **Existing logic-analysis tooling (investigated; leverage selectively, NOT as the direction backbone):**
  - `validate_ladder_logic` → `src/verification/sdk_verifier.py` is **syntactic only** (balanced parens, known-name check vs `COMMON_INSTRUCTIONS` :16, has-output check). **Reuse:** adopt its `COMMON_INSTRUCTIONS` set as the shared "known instruction" vocabulary so `unresolved_instruction` warnings agree with the verifier; optionally run `validate_ladder_logic` as an opt-in pre-flight structural gate. It carries **no** operand direction.
  - Instruction database (`get_instruction`/`get_instruction_syntax` → `src/documentation/instruction_vector_db.py`; 561 instructions in `instruction_vector_cache/instruction_data.pkl`, exact-name lookup `get_instruction_by_name` :238 needs **no** torch/faiss). **Reuse:** a low-precedence *evidence enrichment* source (instruction category + operand-role names/descriptions) to help the worker **explain** a fact — never to assert read/write direction. **Verified caveats:** coverage is uneven — `MOV` is absent; `ADD`/`XIC`/`OTE`/`COP` have empty/unstructured `parameters` (raw help text in `syntax`); no machine-readable direction anywhere. Treat as best-effort, optional, and never authoritative.
  - `src/code_generator/l5x_generator.py` is a pure XML emitter (no analysis); `src/ai_assistant/*` is generation-side. Nothing to reuse for the graph beyond the shared instruction DB above.
  - **Direction backbone stays deterministic:** `LadderParser` `_operation` (:1139) / `_OUTPUT_TYPES` (:1027) reliably cover the common families (incl. MOV, which the DB lacks). The instruction DB's gaps are exactly why it cannot be the sole source of read/write edges.
- **MCP wiring pattern** (4 edits, see Checkpoint 5) — `src/mcp_server/studio5000_mcp_server.py`; integration wrapper `src/tag_analyzer/tag_mcp_integration.py` (:473, try/except + `success` flag).
- **`networkx` 3.6.1** is installed but absent from `requirements.txt` — add `networkx>=3.0`.

### New module layout — `src/comment_graph/`
| File | Purpose |
|---|---|
| `model.py` | Canonical entities/IDs: `EntityKind`, `EntityId`, `Entity`, `SourceLoc`, `normalize_operand`/`base_tag_of`. Pure. |
| `edges.py` | `Relation` enum, `Edge`, `EdgeExtractor` (lifts direction rules into typed reads/writes/feeds). |
| `graph_adapter.py` | `DependencyGraph` over `networkx.MultiDiGraph` — **only** file importing networkx (`predecessors`/`successors`/`sccs`/`condensation`/`topo_order`/`digest`). Keeps rustworkx swap open. |
| `builder.py` | `ModelBuilder` — resolve `.l5x`/`.acd`, parse via `LadderParser` + `inventory_l5x`, build entities+edges → `(DependencyGraph, provenance)`. |
| `facts.py` | `Confidence`, `FactStatus`, `EvidenceKind` (precedence tiers), `Evidence`, `Fact`, `FactUpdate`, `Contradiction`, `FactStore` (monotonic merge + precedence + semantic-change detection). |
| `worker.py` | `Worker` protocol, `WorkerResult`, `AssistanceRequest`, `ModelLevel`, `DeterministicWorker` (default, no LLM), `CallbackWorker` (optional injectable). |
| `scheduler.py` | `Scheduler` — dedup work queue, SCC condensation, topo scheduling, bounded internal passes for cycles, bounded parallel executor, `PassStats`, convergence detection. |
| `orchestrator.py` | `analyze_comment_graph(request) -> AnalysisResult` — full lifecycle. |
| `deliverables_bridge.py` | Converged `Fact`s → UPPERCASE decision dicts → `generate_deliverables`; extends memory record with graph digest + artifact hash around `manage_incremental_memory`. |
| `config.py` | `AnalysisConfig` defaults (`max_passes=8`, `max_component_passes=4`, `max_workers=4`), `AnalysisRequest`/`AnalysisResult` + `to_dict`/`from_dict`. |

### Core data shapes
- **`EntityId(kind, key)`** — canonical keys preserve the exact member/index expression: `op:N101[18]` ≠ `op:N101[20].1`, both linking to `tag:N101`; module I/O keeps full path + a normalized channel identity; `rung:{program}/{routine}/{number}`.
- **`Edge(src, dst, relation, confidence, evidence_id, source_loc, instruction, unresolved)`** — `Relation ∈ {READS, WRITES, FEEDS, ALIAS_OF, CONTAINS, REFERENCES, COMMENT_EVIDENCE}`.
- **`Fact(subject, predicate, value, normalized_value, confidence, evidence_ids, producer_pass, status, rendered_candidate, precedence_tier)`** — semantic equality/change uses `normalized_value` (+confidence+tier), **never prose**.
- **`EvidenceKind`** precedence (enum order = tier): `NATIVE_COMMENT=1, USER_DECISION=2, LOGIC_METADATA=3, PRIOR_MEMORY=4, INSTRUCTION_DOC=5, VECTOR_RETRIEVAL=6, MODEL_INFERENCE=7`. `INSTRUCTION_DOC` = the 561-instruction DB enrichment (operand-role names/descriptions); low precedence, optional, never asserts direction.
- **`WorkerResult(fact_updates, assistance_requests)`**; **`AssistanceRequest(entity_id, predicate, ambiguity, evidence, candidate_values, suggested_model_level, rationale)`**.
- **Decisions** emitted for deliverables keep UPPERCASE keys (`TYPE/SCOPE/NAME/PROPOSED_DESCRIPTION`, optional `CONFIDENCE/RATIONALE/LOGIC_SNIPPET/RUNG_REFERENCES`) so `generate_deliverables`/`manage_incremental_memory` work unchanged.

### Convergence algorithm (scheduler)
Initialize → build graph → seed facts (native comments tier 1, metadata tier 3, prior memory tier 4 guarded by hashes, user seeds tier 2) → enqueue entities needing analysis. Per pass:
1. Select a **deterministic** batch of ready tasks (sorted by `EntityId`) whose deps are stable for the current fact version.
2. Run batch through a **bounded executor**; gather all `WorkerResult`s **without applying**.
3. **Merge single-threaded in sorted `EntityId` order** (arrival order cannot affect state) via `FactStore.merge` → `CHANGED | ENRICHED | REJECTED | CONTRADICTION`.
4. For each **semantic** change, requeue **both predecessors and successors** exactly once.
5. Record `PassStats`.
6. **Stop:** `CONVERGED` (queue empty + no semantic change); `BOUNDED` (hit `max_passes`/`max_component_passes` with work pending — report which); `PARTIAL` (converged but worker errors / unresolved assistance remain); `FAILED` (build/conversion error).

SCC condensation collapses cycles before scheduling; acyclic components run in topological order; cyclic components run ≤ `max_component_passes` internal iterations, each requiring a semantic change to justify the next, and mark leftovers `UNRESOLVED` (**never** emit HIGH confidence from an exhausted cycle).

**Merge precedence:** stronger tier replaces (old → `SUPERSEDED`); same tier + same `normalized_value` enriches/raises confidence (not a semantic change); same tier + different value → deterministic tie-break (confidence, then lexical); weaker tier that contradicts → keep incumbent, emit `Contradiction` (no silent overwrite).

### Deterministic worker + escalation
`DeterministicWorker.analyze(entity, ctx)` walks precedence: (1) native operand/tag/rung comment → HIGH `OBSERVED`; (2) module/IO metadata → MEDIUM/HIGH; (3) instruction read/write semantics — propagate a neighbor's stable fact along `FEEDS` at one confidence step lower (`INFERRED`); (4) optional instruction-DB enrichment (`INSTRUCTION_DOC` tier — operand-role name/description via exact-name `get_instruction_by_name`, no embeddings) to enrich a fact's wording only; (5) optional vector retrieval (off by default). It **escalates** (emits `AssistanceRequest`, never fabricates) when deterministic paths are exhausted AND: ≥2 incompatible FEEDS-derived candidates, or the role depends on an `unresolved` instruction, or only `UNRESOLVED/LOW` neighbor facts exist. `suggest_model_level(candidate_count, neighbor_count, in_cycle, tier1_conflict)` (pure fn): **HAIKU** single mechanical reword; **SONNET** 2–4 candidates or small local subgraph; **OPUS** in-cycle, large neighborhood, or tier-1 comment conflict.

### Concurrency
`asyncio` + bounded `asyncio.Semaphore`; deterministic CPU-light worker offloaded via a shared `ThreadPoolExecutor(max_workers)` (`asyncio.to_thread`); optional LLM `CallbackWorker` is I/O-bound and benefits directly. Workers read only an **immutable `WorkerContext` snapshot** and never touch `FactStore`. Determinism guaranteed by gather-then-merge-in-sorted-order. Cancellation checked between passes/batches; **no deliverables written on cancel**.

## Implementation checkpoints (review after each)

1. **Deps + model/edges foundation.** Add `networkx>=3.0` to `requirements.txt`. Implement `model.py`, `edges.py`, `graph_adapter.py`. Unit tests for operand normalization + per-instruction read/write/feeds extraction against synthetic ladder snippets.
2. **Builder.** `builder.py` — resolve/parse L5X (+ACD via converter), construct entities+edges, validate every parsed source/dest operand has a canonical ID, emit `unresolved_instruction` warnings (no silent edges).
3. **Facts + merge + invalidation + SCC.** `facts.py` `FactStore` (merge/precedence/contradiction/semantic-change) and `scheduler.py` SCC condensation + topo order + queue dedup + predecessor/successor requeue.
4. **Bounded parallel execution + worker.** `worker.py` (`DeterministicWorker` + escalation + `suggest_model_level`) and the bounded async executor with gather-then-sorted-merge. Order-independence + tiering tests.
5. **MCP tool.** `orchestrator.py` + `config.py`, then the **4 wiring edits** in `src/mcp_server/studio5000_mcp_server.py`: (a) `add_tool("analyze_comment_graph", …, self.analyze_comment_graph)` in `_register_tools` (~:793); (b) async delegator on `Studio5000MCPServer` (~:1470) → `self.tag_integration.analyze_comment_graph(...)`; (c) `elif name == 'analyze_comment_graph'` inputSchema block (~:1843) — full schema per spec, `required=['file_path']`; (d) impl on `TagMCPIntegration` (~:519) with the try/except+`success` wrapper (do **not** route the orchestrator through `_get_comment_pipeline`'s reload; only the bridge calls `PLCCommentPipeline`). Add a `--test` smoke path in `main()` (~:1921).
6. **Deliverables + memory integration.** `deliverables_bridge.py` — render only the final state to UPPERCASE decisions → `generate_deliverables` (validate every decision has source/confidence/status); extend memory record additively with `source_artifact_hash`, `graph_digest`, `analysis_config`, `convergence_status`, `last_converged_pass`, per-decision dependency IDs; invalidate dependent decisions by graph edge even when routine XML hash is unchanged.
7. **Tests + smoke.** Full matrix below; run `python -m pytest` and the MCP `--test`.

## Test matrix
**Unit** (`tests/comment_graph/`, tiny synthetic L5X): operand normalization (`N101[18]` vs `N101[20].1` vs base); edge extraction per family; unsupported-instruction (entity retained, no edge); SCC condensation + diamond topo order; fact merge/precedence; contradiction reporting; semantic-change vs prose-only; queue dedup; **order-independent output** (shuffled completion → identical FactStore); memory invalidation by graph dep not routine hash; assistance tiering.

**Integration** (`tests/acd/`, temp output/cache dirs, must not overwrite fixtures):
- **`test_thawroom_n18_n101_regression`** (primary, native L5X): graph has `N18[1]` READ + `N101[18]` WRITE/FEEDS; native operand comment on `N101[18]` seeds a HIGH fact; `N18[1]` is (re)scheduled after that fact lands; downstream temp-control entities invalidated; result reports pass history + provenance; final CSV/HTML contain only converged decisions.
- `test_thawroom_acd_path` (via `convert_acd_to_l5x`, warnings/provenance retained).
- `test_multipass_chain`, `test_diamond`, `test_cycle_bounded`, `test_unsupported_instruction`, `test_contradiction`, `test_bounded_nonconvergence` — each asserts its `convergence_status` and that limits are visible.

## Risks / edge cases
- **No silent edges** for unknown instructions — direction only for instructions whose semantics are known to `_operation`/`_OUTPUT_TYPES`; unknown mnemonics record the entity + `unresolved_instruction` warning and no directional edge. Cross-check names against `sdk_verifier.COMMON_INSTRUCTIONS` so the warning vocabulary matches the existing verifier. Not AOI-fallback direction inference.
- **Alias** (`AliasFor`) → `ALIAS_OF` edge; let facts flow through without double-counting identity.
- **Array/UDT member identity** — three distinct entities linked by `base_tag`; over-merging loses per-channel calibration, under-linking loses base-tag comment inheritance.
- **Oscillation** — compare `normalized_value`, deterministic tie-break, cycle bound.
- **Stale memory** — persist + check `source_artifact_hash` (bytes of resolved L5X) **and** `graph_digest`; refuse reuse if either differs. Additive memory fields keep old files loadable.
- **ACD not lossless** — keep converter `validation`/`note` in `conversion_warnings`; never label converted L5X lossless.
- **Large fixture cost** — 574K L5X parsed once in the end-to-end regression only; synthetic L5X everywhere else.

## Verification
Run from repo root with the project venv:
```powershell
pip install -r requirements.txt          # picks up networkx
python -m pytest                          # full unit + integration matrix
python -m pytest tests/acd/test_thawroom_n18_n101_regression.py -v   # primary regression
python src/mcp_server/studio5000_mcp_server.py --test                # MCP smoke (runs tool on native L5X)
```
Manually invoke the tool on the native fixture with `generate_deliverables=True` to an output dir and confirm the HTML distinguishes observed comments from inferred proposals, and that `convergence_status` / unresolved assistance items / contradictions / cycles appear in the result. Offline output is **not** deployment approval — Studio 5000 import + Verify Controller + FAT remain required.
