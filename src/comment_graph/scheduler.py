"""Deterministic work scheduling over the dependency graph.

This module owns the *mechanics* of convergence: a deduplicated work queue, a
stable topological batch order derived from SCC condensation, and neighbour
requeue on semantic change. The bounded parallel *executor* that actually runs a
worker over each batch is added in ``run_passes`` (Checkpoint 4) and consumes
these mechanics.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import EntityId
from .graph_adapter import DependencyGraph
from .config import AnalysisConfig
from .facts import FactStore, MergeOutcome


@dataclass
class PassStats:
    pass_no: int
    scheduled: int = 0
    changed: int = 0
    enriched: int = 0
    rejected: int = 0
    contradictions: int = 0
    assistance: int = 0
    errors: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "pass": self.pass_no,
            "scheduled": self.scheduled,
            "changed": self.changed,
            "enriched": self.enriched,
            "rejected": self.rejected,
            "contradictions": self.contradictions,
            "assistance": self.assistance,
            "errors": self.errors,
        }


class Scheduler:
    """A deterministic, deduplicated scheduler with topo-ordered batches."""

    def __init__(self, graph: DependencyGraph, config: AnalysisConfig) -> None:
        self.graph = graph
        self.config = config
        self._queue: List[EntityId] = []
        self._queued: set[EntityId] = set()
        self._rank, self._component = self._index_components()

    def _index_components(self):
        """Precompute a topo rank per node and its SCC membership."""
        rank: Dict[EntityId, int] = {}
        component: Dict[EntityId, List[EntityId]] = {}
        for i, comp in enumerate(self.graph.topo_components()):
            for node in comp:
                rank[node] = i
                component[node] = comp
        return rank, component

    # -- queue ------------------------------------------------------------
    def enqueue(self, entity: EntityId) -> None:
        if entity in self._queued:
            return
        self._queued.add(entity)
        self._queue.append(entity)

    def enqueue_all(self, entities) -> None:
        for entity in entities:
            self.enqueue(entity)

    def requeue_neighbors(self, entity: EntityId) -> None:
        """Enqueue both predecessors and successors of a changed entity."""
        for neighbor in self.graph.predecessors(entity):
            self.enqueue(neighbor)
        for neighbor in self.graph.successors(entity):
            self.enqueue(neighbor)

    def ready_batch(self) -> List[EntityId]:
        """Return all queued entities in a stable topo order and clear the queue.

        Ordering: SCC-condensation topological rank, then EntityId string. This
        makes the batch order independent of enqueue order.
        """
        batch = sorted(
            self._queue,
            key=lambda e: (self._rank.get(e, len(self._rank)), str(e)),
        )
        self._queue = []
        self._queued = set()
        return batch

    def is_empty(self) -> bool:
        return not self._queue

    # -- structure --------------------------------------------------------
    def component_of(self, entity: EntityId) -> List[EntityId]:
        return self._component.get(entity, [entity])

    def in_cycle(self, entity: EntityId) -> bool:
        return len(self.component_of(entity)) > 1


async def execute_batch(worker, contexts, max_workers: int):
    """Run ``worker.analyze`` over each context under a bounded semaphore.

    The (CPU-light, side-effect-free) worker is offloaded via ``asyncio.to_thread``
    so an optional I/O-bound callback worker benefits directly. Results are
    returned **sorted by EntityId**, so a caller that merges them in this order
    gets a state independent of completion timing.
    """
    semaphore = asyncio.Semaphore(max_workers)

    async def run_one(entity: EntityId, ctx):
        async with semaphore:
            result = await asyncio.to_thread(worker.analyze, ctx)
            return entity, result

    pairs = await asyncio.gather(*(run_one(e, c) for e, c in contexts.items()))
    return sorted(pairs, key=lambda pair: str(pair[0]))


def apply_results(
    fact_store: FactStore,
    sorted_pairs: List[Tuple[EntityId, object]],
    pass_no: int,
) -> Tuple[List[EntityId], PassStats]:
    """Merge worker results **single-threaded in sorted order** and tally stats.

    Returns the list of subjects that underwent a semantic change (to requeue)
    and the pass statistics. Merging in the pre-sorted order is what guarantees
    arrival order cannot affect the resulting FactStore.
    """
    stats = PassStats(pass_no, scheduled=len(sorted_pairs))
    changed: List[EntityId] = []
    for _entity, result in sorted_pairs:
        for update in result.fact_updates:
            outcome = fact_store.merge(update, pass_no)
            if outcome.outcome is MergeOutcome.CHANGED:
                stats.changed += 1
            elif outcome.outcome is MergeOutcome.ENRICHED:
                stats.enriched += 1
            elif outcome.outcome is MergeOutcome.REJECTED:
                stats.rejected += 1
            elif outcome.outcome is MergeOutcome.CONTRADICTION:
                stats.contradictions += 1
            if outcome.semantic_changed:
                changed.append(update.subject)
        stats.assistance += len(result.assistance_requests)
    return changed, stats
