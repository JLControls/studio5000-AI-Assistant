"""Bounded async executor: gather-then-sorted-merge order independence (Ckpt 4)."""

import asyncio

from comment_graph.model import Confidence, operand_entity
from comment_graph.facts import Evidence, EvidenceKind, FactStatus, FactStore, FactUpdate
from comment_graph.worker import WorkerContext, WorkerResult
from comment_graph.scheduler import execute_batch, apply_results


def op(name):
    return operand_entity(name)


def _update(entity, value):
    return FactUpdate(
        subject=entity,
        predicate="description",
        value=value,
        normalized_value=value,
        confidence=Confidence.MEDIUM,
        evidence=[Evidence(kind=EvidenceKind.LOGIC_METADATA, detail=value)],
        status=FactStatus.OBSERVED,
    )


class _StubWorker:
    """Returns a fact per entity, sleeping a per-entity amount to shuffle
    completion order (proving the executor's sort makes merges deterministic)."""

    def __init__(self, delays):
        self._delays = delays

    def analyze(self, ctx: WorkerContext) -> WorkerResult:
        import time

        time.sleep(self._delays.get(str(ctx.entity), 0))
        return WorkerResult(fact_updates=[_update(ctx.entity, f"desc-{ctx.entity.key}")])


def _contexts(names):
    return {op(n): WorkerContext(entity=op(n)) for n in names}


class TestExecuteBatch:
    def test_results_sorted_by_entity_id(self):
        worker = _StubWorker({})
        contexts = _contexts(["C", "A", "B"])
        pairs = asyncio.run(execute_batch(worker, contexts, max_workers=4))
        assert [str(e) for e, _ in pairs] == ["op:A", "op:B", "op:C"]

    def test_sorted_despite_shuffled_completion(self):
        # A finishes slowest, C fastest -> completion order != id order.
        worker = _StubWorker({"op:A": 0.05, "op:B": 0.02, "op:C": 0.0})
        contexts = _contexts(["A", "B", "C"])
        pairs = asyncio.run(execute_batch(worker, contexts, max_workers=4))
        assert [str(e) for e, _ in pairs] == ["op:A", "op:B", "op:C"]


class TestOrderIndependentMerge:
    def _run(self, delays):
        worker = _StubWorker(delays)
        contexts = _contexts(["A", "B", "C"])
        pairs = asyncio.run(execute_batch(worker, contexts, max_workers=4))
        store = FactStore()
        apply_results(store, pairs, pass_no=1)
        return {str(f.subject): f.value for f in store.facts()}

    def test_final_store_identical_regardless_of_timing(self):
        fast_a = self._run({"op:A": 0.05, "op:C": 0.0})
        fast_c = self._run({"op:C": 0.05, "op:A": 0.0})
        assert fast_a == fast_c
        assert fast_a == {"op:A": "desc-A", "op:B": "desc-B", "op:C": "desc-C"}


class TestApplyResultsStats:
    def test_counts_changes_and_assistance(self):
        store = FactStore()
        pairs = asyncio.run(execute_batch(_StubWorker({}), _contexts(["A", "B"]), 4))
        changed, stats = apply_results(store, pairs, pass_no=2)
        assert stats.scheduled == 2
        assert stats.changed == 2
        assert set(str(e) for e in changed) == {"op:A", "op:B"}
