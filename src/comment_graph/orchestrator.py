"""End-to-end lifecycle: build graph -> seed facts -> converge -> collect state.

``analyze_comment_graph`` is the single entry point the MCP tool calls. It owns
no XML/CSV logic itself — building is delegated to ``ModelBuilder``, deliverable
rendering to ``deliverables_bridge`` (Checkpoint 6). Here we only run the fixed
point and assemble an ``AnalysisResult``.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .model import (
    Confidence,
    EntityId,
    EntityKind,
    base_tag_of,
    is_placeholder_comment,
    operand_entity,
    tag_entity,
)
from .facts import (
    Evidence,
    EvidenceKind,
    FactStatus,
    FactStore,
    FactUpdate,
)
from .edges import Relation
from .builder import ModelBuilder, BuildResult
from .worker import DeterministicWorker, WorkerContext
from .scheduler import Scheduler, execute_batch, apply_results
from .config import (
    AnalysisConfig,
    AnalysisRequest,
    AnalysisResult,
    ConvergenceStatus,
)

# Only operands are comment *targets*: they are what appears in the logic. TAG
# nodes exist to carry tag-level comments/descriptions into the operands that
# reference them, so they are seeded but never analyzed or proposed.
_ANALYZABLE = (EntityKind.OPERAND,)


async def analyze_comment_graph(request: AnalysisRequest) -> AnalysisResult:
    """Run the full convergence lifecycle and return a structured result."""
    builder = ModelBuilder()
    build = builder.build(request.file_path)
    config = request.config

    fact_store = FactStore()
    native_comments, metadata = _seed(build, fact_store, request)

    scheduler = Scheduler(build.graph, config)
    analyzable = [n for n in build.graph.nodes() if n.kind in _ANALYZABLE]
    scheduler.enqueue_all(analyzable)

    worker = DeterministicWorker()
    pass_history: List[Dict] = []
    assistance: List[Dict] = []
    pass_no = 0
    last_converged_pass = 0

    while not scheduler.is_empty() and pass_no < config.max_passes:
        pass_no += 1
        batch = [e for e in scheduler.ready_batch() if e.kind in _ANALYZABLE]
        contexts = {
            e: _context(e, build, fact_store, scheduler, native_comments, metadata)
            for e in batch
        }
        pairs = await execute_batch(worker, contexts, config.max_workers)
        changed, stats = apply_results(fact_store, pairs, pass_no)
        for _entity, result in pairs:
            for req in result.assistance_requests:
                assistance.append(req.to_dict())
        for subject in changed:
            scheduler.requeue_neighbors(subject)
        pass_history.append(stats.to_dict())
        if stats.changed or stats.enriched:
            last_converged_pass = pass_no

    bounded = pass_no >= config.max_passes and not scheduler.is_empty()
    if bounded:
        status = ConvergenceStatus.BOUNDED
    elif assistance or fact_store.contradictions:
        status = ConvergenceStatus.PARTIAL
    else:
        status = ConvergenceStatus.CONVERGED

    decisions = _decisions(build, fact_store, native_comments)
    provenance = dict(build.provenance)
    provenance["analysis_config"] = config.to_dict()

    result = AnalysisResult(
        convergence_status=status,
        decisions=decisions,
        provenance=provenance,
        warnings=build.warnings,
        contradictions=[
            {
                "subject": str(c.subject),
                "predicate": c.predicate,
                "incumbent": c.incumbent_value,
                "rejected": c.rejected_value,
                "reason": c.reason,
            }
            for c in fact_store.contradictions
        ],
        assistance_requests=assistance,
        pass_history=pass_history,
        last_converged_pass=last_converged_pass,
    )

    # Render deliverables/memory ONLY from the converged state, if requested.
    if request.generate_deliverables and (request.output_dir or request.memory_file_path):
        from .deliverables_bridge import DeliverablesBridge

        result.deliverables = await DeliverablesBridge().render(result, request)

    return result


# -- seeding --------------------------------------------------------------
def _seed(build: BuildResult, fact_store: FactStore, request: AnalysisRequest):
    """Seed native comments, metadata, and user decisions; return lookup maps."""
    inventory = build.inventory
    native_comments: Dict[EntityId, str] = {}
    metadata: Dict[EntityId, str] = {}

    # Native operand/tag comments (tier 1). Migration-generated placeholder text
    # is NOT a real comment: skip it so the operand is treated as uncommented and
    # gets a proposed comment instead of being taken as authoritative.
    for (tag, suffix), text in inventory.get("operand_comments", {}).items():
        if not text or is_placeholder_comment(text):
            continue
        if suffix:
            entity = operand_entity(f"{tag}{suffix}")
        else:
            entity = tag_entity(tag)
        native_comments[entity] = text

    # Tag descriptions -> metadata (tier 3). Placeholders skipped here too.
    for key, text in inventory.get("descriptions", {}).items():
        if key.startswith("Tag:") and "/" not in key and not is_placeholder_comment(text):
            metadata[tag_entity(key[len("Tag:"):])] = text

    # Seed facts into the store at pass 0 so propagation has a base.
    for entity, text in native_comments.items():
        _seed_fact(fact_store, entity, text, Confidence.HIGH,
                   FactStatus.OBSERVED, EvidenceKind.NATIVE_COMMENT)
    for entity, text in metadata.items():
        if fact_store.get(entity, "description") is None:
            _seed_fact(fact_store, entity, text, Confidence.MEDIUM,
                       FactStatus.OBSERVED, EvidenceKind.LOGIC_METADATA)

    # User-supplied decisions (tier 2) override metadata but not native comments.
    for seed in request.user_seeds:
        entity = _entity_from_seed(seed)
        if entity is None:
            continue
        value = seed.get("PROPOSED_DESCRIPTION") or seed.get("value", "")
        if value:
            _seed_fact(fact_store, entity, value, Confidence.HIGH,
                       FactStatus.OBSERVED, EvidenceKind.USER_DECISION)

    return native_comments, metadata


def _seed_fact(store, entity, text, confidence, status, kind):
    from .worker import _normalize

    store.merge(
        FactUpdate(
            subject=entity,
            predicate="description",
            value=text,
            normalized_value=_normalize(text),
            confidence=confidence,
            evidence=[Evidence(kind=kind, detail=text, source="seed")],
            status=status,
            rendered_candidate=text,
        ),
        pass_no=0,
    )


def _entity_from_seed(seed: Dict) -> Optional[EntityId]:
    name = seed.get("NAME") or seed.get("entity")
    if not name:
        return None
    if "[" in name or "." in name:
        return operand_entity(name)
    return tag_entity(name)


# -- per-entity context ---------------------------------------------------
def _context(entity, build, fact_store, scheduler, native_comments, metadata):
    base_tag = tag_entity(base_tag_of(entity.key))

    # An operand inherits its base tag's native comment / description as its own
    # identity (same confidence), rather than paying a stepped-down FEEDS hop.
    native = native_comments.get(entity) or native_comments.get(base_tag)
    meta = metadata.get(entity) or metadata.get(base_tag)

    # Data-flow neighbours are FEEDS edges only; tag identity is handled above.
    incident = build.graph.in_edges(entity) + build.graph.out_edges(entity)
    flow_neighbors = set()
    for edge in incident:
        if edge.relation is Relation.FEEDS:
            flow_neighbors.add(edge.src if edge.dst == entity else edge.dst)
    neighbor_facts = tuple(
        f for n in sorted(flow_neighbors, key=str)
        if (f := fact_store.get(n, "description")) is not None
    )

    unresolved = any(edge.unresolved for edge in incident)
    return WorkerContext(
        entity=entity,
        native_comment=native,
        metadata=meta,
        neighbor_facts=neighbor_facts,
        unresolved_instruction=unresolved,
        in_cycle=scheduler.in_cycle(entity),
    )


# -- decisions ------------------------------------------------------------
def _decisions(build, fact_store, native_comments) -> List[Dict]:
    """Emit an UPPERCASE decision per entity that gained a proposed comment.

    Only entities WITHOUT a native comment are proposals; entities that already
    carry a native comment are observations, not deliverables.
    """
    decisions: List[Dict] = []
    for fact in fact_store.facts():
        if fact.subject.kind not in _ANALYZABLE:
            continue
        if fact.subject in native_comments:
            continue  # already commented in the project
        # Scalar operand whose base tag already carries a native comment: the
        # tag comment covers it, so don't propose a duplicate.
        base = base_tag_of(fact.subject.key)
        if fact.subject.key == base and tag_entity(base) in native_comments:
            continue
        if fact.status is FactStatus.SUPERSEDED:
            continue
        name = fact.subject.key
        scope = "Operand"
        decisions.append(
            {
                "TYPE": "Tag",
                "SCOPE": scope,
                "NAME": name,
                "PROPOSED_DESCRIPTION": fact.rendered_candidate,
                "CONFIDENCE": fact.confidence.name,
                "STATUS": fact.status.value,
                "RATIONALE": f"tier={fact.precedence_tier}, pass={fact.producer_pass}",
                "DEPENDENCY_IDS": [str(n) for n in build.graph.predecessors(fact.subject)],
            }
        )
    return decisions
