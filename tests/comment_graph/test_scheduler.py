"""Unit tests for scheduling mechanics: dedup, topo order, requeue (Checkpoint 3)."""

from comment_graph.model import operand_entity
from comment_graph.edges import Edge, Relation
from comment_graph.graph_adapter import DependencyGraph
from comment_graph.scheduler import Scheduler
from comment_graph.config import AnalysisConfig


def _feeds(a, b):
    return Edge(operand_entity(a), operand_entity(b), Relation.FEEDS)


def _graph(*pairs):
    g = DependencyGraph()
    for a, b in pairs:
        g.add_edge(_feeds(a, b))
    return g


def op(name):
    return operand_entity(name)


class TestQueueDedup:
    def test_same_entity_enqueued_once(self):
        sched = Scheduler(_graph(("A", "B")), AnalysisConfig())
        sched.enqueue(op("A"))
        sched.enqueue(op("A"))
        batch = sched.ready_batch()
        assert batch.count(op("A")) == 1

    def test_ready_batch_clears_queue(self):
        sched = Scheduler(_graph(("A", "B")), AnalysisConfig())
        sched.enqueue(op("A"))
        sched.ready_batch()
        assert sched.is_empty()


class TestTopoOrdering:
    def test_ready_batch_sorted_topologically(self):
        g = _graph(("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"))
        sched = Scheduler(g, AnalysisConfig())
        for name in ("D", "C", "B", "A"):
            sched.enqueue(op(name))
        batch = sched.ready_batch()
        pos = {n: i for i, n in enumerate(batch)}
        assert pos[op("A")] < pos[op("B")] < pos[op("D")]
        assert pos[op("A")] < pos[op("C")] < pos[op("D")]

    def test_batch_is_deterministic_regardless_of_enqueue_order(self):
        g = _graph(("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"))
        s1 = Scheduler(g, AnalysisConfig())
        for name in ("A", "B", "C", "D"):
            s1.enqueue(op(name))
        s2 = Scheduler(g, AnalysisConfig())
        for name in ("D", "C", "B", "A"):
            s2.enqueue(op(name))
        assert s1.ready_batch() == s2.ready_batch()


class TestRequeue:
    def test_requeues_predecessors_and_successors(self):
        # A -> B -> C ; a change on B should requeue both A and C.
        g = _graph(("A", "B"), ("B", "C"))
        sched = Scheduler(g, AnalysisConfig())
        sched.requeue_neighbors(op("B"))
        batch = sched.ready_batch()
        assert set(batch) == {op("A"), op("C")}

    def test_requeue_is_deduplicated(self):
        g = _graph(("A", "B"), ("X", "B"), ("B", "C"))
        sched = Scheduler(g, AnalysisConfig())
        sched.requeue_neighbors(op("B"))
        sched.requeue_neighbors(op("B"))
        batch = sched.ready_batch()
        assert sorted(batch, key=str) == [op("A"), op("C"), op("X")]


class TestCycleAwareness:
    def test_cycle_members_scheduled_together(self):
        g = _graph(("A", "B"), ("B", "A"), ("B", "C"))
        sched = Scheduler(g, AnalysisConfig())
        for name in ("A", "B", "C"):
            sched.enqueue(op(name))
        batch = sched.ready_batch()
        # C depends on the {A,B} cycle, so it comes last.
        assert batch[-1] == op("C")

    def test_reports_component_of_entity(self):
        g = _graph(("A", "B"), ("B", "A"))
        sched = Scheduler(g, AnalysisConfig())
        assert set(sched.component_of(op("A"))) == {op("A"), op("B")}
