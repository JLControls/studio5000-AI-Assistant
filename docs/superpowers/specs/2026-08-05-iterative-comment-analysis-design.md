# Iterative and Parallel PLC Comment Analysis

## Goal

Add a server-side MCP workflow that analyzes PLC tags and logic to a converged state instead of relying on the calling agent to repeat one-shot context queries manually.

The workflow must:

- discover verified read/write relationships from L5X or ACD-derived L5X;
- propagate new tag and logic facts to dependent and predecessor components;
- analyze independent work in parallel;
- stop at a deterministic fixed point or a bounded, diagnosable limit; and
- generate comment deliverables only from the converged analysis state.

The existing primitive tools remain available for diagnostics, targeted inspection, and advanced callers. The new orchestrator is the supported public workflow for project-wide comment analysis.

## Problem and verified baseline

The current comment pipeline separates context extraction from decision generation. `get_tag_reasoning_context` reads a target tag and its rung references once, `generate_comment_deliverables` serializes caller-supplied decisions, and `manage_comment_memory` records hashes and decisions without dependency invalidation.

The current L5X chunk dependency extractor also records only the destination for `MOV` and `ADD` patterns. It does not expose a complete read/write graph, and the comment context map reads tag-level comments but not operand comments.

The thaw-room fixture demonstrates the failure mode:

```text
MOVE(ENETBRIDGE_5069:1:I.Ch00.Data,N18[1])
ADD(N18[1],1,N101[18])
```

The native artifact describes `N101[18]` as the calibrated temperature for Thawing Room 1 RTD A. That fact should improve the interpretation of `N18[1]`, and the improved interpretation should be available to any later analysis of the scaling and control logic. The current workflow does not requeue `N18`, the rung, or downstream consumers.

The implementation must treat the native L5X as authoritative when it is available. For an ACD input, use the existing offline ACD-to-L5X conversion path and retain conversion warnings and provenance in the analysis result. Offline analysis remains separate from Studio 5000 import, controller verification, and FAT approval.

## Scope

### In scope

- A new project-wide comment-analysis orchestrator exposed as an MCP tool.
- Canonical PLC entities for tags, operands, rungs, routines, programs, modules, and existing comments.
- A typed directed dependency graph with read, write, alias, containment, and evidence relationships.
- Iterative fact propagation with predecessor invalidation and downstream impact tracking.
- Bounded parallel execution for independent graph work.
- Cycle-aware convergence, confidence handling, provenance, and unresolved-work reporting.
- Integration with existing comment memory and deliverable generation.
- Regression and integration tests using the thaw-room ACD and native L5X fixture.

### Out of scope

- Automatic modification of controller logic or tag values.
- Automatic approval or import into Studio 5000.
- Replacing the L5X parser or ACD converter.
- Treating vector similarity as proof of a PLC dependency.
- Building a second general-purpose graph database service.
- Adding drawing/OCR evidence to the first implementation unless an existing indexed drawing result is explicitly supplied as an evidence source.

## Design decisions

### Server-side orchestration

Add a public MCP tool named `analyze_comment_graph` that owns the complete lifecycle:

1. resolve and parse the input artifact;
2. construct the canonical model and dependency graph;
3. seed the fact store from existing comments and caller-provided evidence;
4. schedule analysis work;
5. propagate changed facts until convergence or a bounded stop condition;
6. return the analysis report and converged decisions; and
7. optionally generate the existing CSV and HTML deliverables.

The existing `get_uncommented_tags`, `get_tag_reasoning_context`, `generate_comment_deliverables`, and `manage_comment_memory` tools remain unchanged in their basic contracts. The orchestrator may reuse their parsing and rendering helpers, but must not require the client to coordinate their calls.

### Graph library rather than custom traversal

Use a mature graph library behind a small project-specific adapter. The initial implementation should use `networkx` because it provides directed multigraphs, predecessor/successor queries, strongly connected components, condensation graphs, and topological scheduling without requiring a service or native build. Keep graph-specific calls inside an adapter so `rustworkx` can replace it if fixture benchmarks show that graph construction or traversal is a bottleneck.

The graph library is responsible for graph storage and standard algorithms. PLC-specific parsing, operand normalization, edge semantics, evidence precedence, and convergence policy remain project code.

Do not add a graph database server or persistent graph store for this feature. Persist the normalized graph digest and fact/provenance state through the existing project-scoped memory file only when requested.

### Monotonic fact updates

Facts must be versioned and mergeable. A new observation may:

- add evidence;
- increase or decrease confidence;
- replace a provisional interpretation with a stronger one; or
- mark a prior proposal as superseded.

The orchestrator must not oscillate between equivalent prose descriptions. Separate stable semantic facts from rendered wording, compare semantic fact values before scheduling dependents, and use deterministic tie-breaking for equal-confidence alternatives.

## Canonical model

Create a normalized model independent of XML element layout:

```text
Project
  Program
    Routine
      Rung
        Instruction / Operand
  Tag
    TagMember or ArrayElement
  Module / IOPoint
```

Each entity has a stable ID, source location, normalized name, scope, data type where known, and source hash. Operand IDs must preserve both the base tag and the member/index expression. For example, `N101[18]` is distinct from `N101[20].1`, while both retain a link to base tag `N101`.

Normalize equivalent names without losing the original spelling:

- array/member operands retain their exact expression and expose a base-tag relation;
- module I/O paths retain the full path and a normalized channel identity;
- aliases expose an alias edge to the target tag;
- constants are represented as operands but are not scheduled as tags;
- instruction names are not treated as tags;
- case handling follows Logix tag semantics and must be deterministic.

## Dependency graph

Use a directed multigraph. Every edge carries a typed relation, source location, confidence, and evidence reference.

Required edge types:

- `reads`: instruction or rung reads an operand;
- `writes`: instruction or rung writes an operand;
- `feeds`: a value-producing operand feeds a consuming operand through an instruction;
- `alias_of`: alias tag points to its target;
- `contains`: project-to-program-to-routine-to-rung containment;
- `references`: a rung/routine references a tag or module; and
- `comment_evidence`: existing tag, operand, rung, routine, or external evidence supports an entity.

At minimum, parse source and destination operands for:

- `MOV`, `COP`, `CPS`, `CPT`, `ADD`, `SUB`, `MUL`, `DIV`, and other recognized output instructions;
- `XIC`, `XIO`, `ONS`, `OTE`, `OTL`, `OTU`, timer/counter instructions, and compare instructions; and
- instruction forms already supported by the repository’s ladder parser.

Unknown instructions must remain in the model with an `unresolved_instruction` warning. They must not silently create incomplete dependency edges.

For an instruction such as `ADD(N18[1],1,N101[18])`, the graph must contain evidence that the instruction reads `N18[1]`, writes `N101[18]`, and feeds the destination from the source operands. The graph must support both forward impact (`N18` affects `N101`) and reverse invalidation (`N101` becoming better understood causes `N18` and the producing rung to be revisited).

## Fact and evidence store

Maintain a project-scoped fact store keyed by canonical entity ID. Each fact record contains:

- semantic subject and predicate, such as `N101[18] / role / calibrated_temperature`;
- value and normalized value used for equality checks;
- confidence (`high`, `medium`, `low`, or `unresolved`);
- evidence IDs and source locations;
- producer/pass number;
- status (`observed`, `inferred`, `proposed`, `superseded`, or `unresolved`); and
- rendered comment candidate, if one exists.

Existing evidence precedence is:

1. native L5X tag, operand, and rung comments;
2. explicit user-supplied decisions or evidence;
3. verified logic structure and I/O/module metadata;
4. prior project memory marked as accepted or reviewed;
5. semantic/vector retrieval; and
6. model inference without corroborating evidence.

Lower-precedence evidence may enrich a fact but must not overwrite stronger contradictory evidence silently. Contradictions must be returned in the report.

The fact store is an analysis snapshot. Existing `manage_comment_memory` may persist the final snapshot, but persistence must include the graph digest and input artifact hash so stale facts cannot be reused against a different project export.

## Iterative scheduling algorithm

Use a work queue of analysis tasks. A task targets one entity or a small strongly connected component and includes the fact-store version it observed.

### Initialization

1. Resolve `.l5x` directly or convert `.acd` through the existing offline converter.
2. Parse all available tags, operands, modules, routines, rungs, instructions, and existing comments.
3. Build the graph and validate that every parsed source/destination operand has a canonical ID.
4. Seed facts from comments, metadata, prior accepted memory, and explicit input evidence.
5. Enqueue entities with missing comments, unresolved roles, changed source hashes, or dependencies whose facts are newly available.

### Pass execution

For each pass:

1. Take a deterministic batch of ready tasks whose dependencies are stable for the current fact version.
2. Run independent tasks concurrently through a bounded executor. The worker must be isolated from shared mutable state and return proposed fact updates plus evidence.
3. Merge updates in a deterministic order using the fact conflict policy.
4. Identify facts whose semantic value or confidence changed materially.
5. Traverse graph predecessors and successors through the graph adapter and enqueue affected entities exactly once for the next eligible batch.
6. Record pass statistics, changed facts, newly scheduled entities, rejected updates, and errors.
7. Stop when the queue is empty and no merge changed the semantic state.

Use a configurable worker limit with a conservative default. The MCP request must remain responsive through asynchronous execution, but the result must not depend on completion order.

### Cycles and convergence

Collapse strongly connected components before scheduling. Analyze acyclic components in topological order. For cyclic components:

- run bounded internal passes;
- require semantic fact changes to justify another pass;
- retain the best-supported facts if the component stabilizes;
- mark unresolved or oscillating facts explicitly when the bound is reached; and
- never emit a high-confidence comment solely because a cycle exhausted its pass budget.

Default limits must be explicit in the request/result, such as `max_passes`, `max_component_passes`, and `max_workers`. The response must state whether convergence was achieved, bounded, or failed.

## MCP interface

Register a new tool with a schema equivalent to:

```json
{
  "name": "analyze_comment_graph",
  "input": {
    "file_path": "path to ACD or L5X",
    "scope_filter": "optional program or routine",
    "seed_decisions": "optional proposed or accepted decisions",
    "evidence": "optional structured evidence records",
    "max_passes": 8,
    "max_component_passes": 4,
    "max_workers": 4,
    "generate_deliverables": false,
    "output_dir": "required only when deliverables are requested",
    "project_name": "optional report name",
    "persist_memory": false,
    "memory_file_path": "required only when memory persistence is requested"
  }
}
```

The response must include:

- `success` and `convergence_status`;
- resolved input path, source type, artifact hash, and conversion warnings;
- graph counts by entity and edge type;
- pass count, worker count, queue statistics, and per-pass changes;
- converged decisions with confidence, provenance, and affected entities;
- unresolved entities, unsupported instructions, contradictions, cycles, and errors;
- memory impact, if persistence was requested; and
- deliverable paths only after successful generation from the final state.

The existing primitive tools should remain useful for inspecting a failed or bounded run. The orchestrator should return stable entity IDs and source locations that can be passed to `get_tag_reasoning_context`.

## Deliverable and memory integration

Do not write the CSV or HTML report after each pass. Render only the final fact state. Include pass/provenance metadata in the HTML report so an engineer can distinguish observed comments from inferred proposals.

When `generate_deliverables` is false, return decisions in the MCP result without writing files. When true, use the existing `generate_comment_deliverables` implementation after validating that every emitted decision has a source, confidence, and status.

Extend comment memory records with:

- source artifact hash;
- graph digest;
- analysis configuration;
- convergence status;
- last converged pass; and
- dependency/evidence IDs for each saved decision.

A decision change must invalidate every predecessor and successor whose semantic interpretation depends on that decision, even if the underlying XML routine hash is unchanged.

## Error handling and safety

- Missing files, unsupported extensions, conversion failures, malformed XML, and graph-construction errors return structured MCP errors.
- ACD conversion warnings are preserved; a parseable converted L5X is not described as lossless.
- Unknown instruction syntax creates an unresolved warning and prevents unsupported relationships from being treated as verified.
- Worker failures are isolated to their tasks and included in the result. The run may converge with partial coverage only if `convergence_status` says `partial` and unresolved work is listed.
- Cancellation must stop new work, allow in-flight tasks to finish or cancel safely, and never write partial deliverables.
- No generated comment or logic change is deployment approval. Studio 5000 import/Verify Controller, scan-time review, and FAT remain required.

## Testing strategy

Add focused tests under `tests/` and `tests/acd/`.

### Unit tests

- canonical operand normalization for tags, members, arrays, aliases, module I/O, and constants;
- source/read and destination/write extraction for every supported instruction family;
- graph predecessor/successor queries and strongly connected component condensation;
- deterministic fact merging, confidence precedence, contradiction reporting, and semantic-change detection;
- queue deduplication and bounded scheduling;
- stable output regardless of worker completion order; and
- memory invalidation based on graph dependencies rather than routine hashes alone.

### Integration tests

Use the thaw-room ACD and matching native L5X as the real fixture. The primary regression must prove:

1. the graph contains the `N18[1]` read and `N101[18]` write/feeds relationship;
2. the native operand comment for `N101[18]` seeds a fact;
3. analysis of `N18[1]` is scheduled or rerun after the `N101[18]` fact becomes available;
4. downstream temperature-control entities are invalidated when the upstream interpretation changes;
5. the final result reports pass history and provenance; and
6. the final CSV/HTML contains only converged decisions.

Additional fixture tests must cover a multi-pass chain, a diamond-shaped dependency graph, a cyclic graph, an unsupported instruction, a contradictory comment, and a bounded non-converging component.

### Validation commands

Run from the repository root with the project virtual environment:

```powershell
python -m pytest
python src/mcp_server/studio5000_mcp_server.py --test
```

The ACD integration tests must use temporary output/cache directories and must not overwrite the authoritative native L5X or the supplied ACD.

## Acceptance criteria

The fix is complete when:

- the new MCP tool performs project-wide iterative analysis without client-managed repeated calls;
- independent work executes through bounded parallel scheduling with deterministic results;
- source/destination and predecessor/successor relationships are available for supported logic;
- a changed fact requeues all materially affected entities, including upstream producers;
- cycles, contradictions, unsupported instructions, and pass limits are visible in the result;
- deliverables are emitted only from a converged or explicitly partial final state;
- comment memory invalidates dependent decisions even when routine XML hashes do not change;
- the thaw-room `N18[1]`/`N101[18]` regression passes; and
- existing primitive MCP tools and deliverable formats remain backward compatible.

## Implementation sequencing

1. Add `networkx` as a runtime dependency and add dependency/fact model tests using synthetic ladder snippets.
2. Add the graph adapter and canonical L5X/ACD model builder.
3. Add operand comment ingestion and bidirectional edge extraction.
4. Add fact merging, invalidation, SCC scheduling, and bounded parallel execution.
5. Add the MCP tool and integrate final-state deliverables/memory.
6. Add thaw-room integration tests and deterministic/concurrency tests.
7. Run the MCP smoke test and full pytest suite, then review generated reports without treating offline output as deployment approval.
