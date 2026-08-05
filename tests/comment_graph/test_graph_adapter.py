"""Unit tests for the networkx-backed DependencyGraph (Checkpoint 1)."""

from comment_graph.model import operand_entity
from comment_graph.edges import Edge, Relation
from comment_graph.graph_adapter import DependencyGraph


def _feeds(a: str, b: str) -> Edge:
    return Edge(operand_entity(a), operand_entity(b), Relation.FEEDS)


def _graph(*pairs) -> DependencyGraph:
    g = DependencyGraph()
    for a, b in pairs:
        g.add_edge(_feeds(a, b))
    return g


class TestNodesAndEdges:
    def test_add_edge_creates_endpoints(self):
        g = _graph(("A", "B"))
        assert g.has_node(operand_entity("A"))
        assert g.has_node(operand_entity("B"))

    def test_nodes_returned_sorted_deterministically(self):
        g = _graph(("B", "C"), ("A", "B"))
        assert [str(n) for n in g.nodes()] == ["op:A", "op:B", "op:C"]

    def test_add_explicit_node(self):
        g = DependencyGraph()
        g.add_entity(operand_entity("Lonely"))
        assert g.has_node(operand_entity("Lonely"))


class TestNeighbors:
    def test_predecessors_follow_edge_direction(self):
        g = _graph(("A", "B"), ("X", "B"))
        preds = g.predecessors(operand_entity("B"))
        assert set(preds) == {operand_entity("A"), operand_entity("X")}

    def test_successors_follow_edge_direction(self):
        g = _graph(("A", "B"), ("A", "C"))
        succs = g.successors(operand_entity("A"))
        assert set(succs) == {operand_entity("B"), operand_entity("C")}

    def test_neighbors_are_deduplicated_across_parallel_edges(self):
        g = DependencyGraph()
        g.add_edge(_feeds("A", "B"))
        g.add_edge(Edge(operand_entity("A"), operand_entity("B"), Relation.READS))
        assert g.successors(operand_entity("A")) == [operand_entity("B")]


class TestSCC:
    def test_cycle_grouped_into_one_component(self):
        g = _graph(("A", "B"), ("B", "A"), ("B", "C"))
        comps = g.sccs()
        cycle = [c for c in comps if len(c) > 1]
        assert len(cycle) == 1
        assert set(cycle[0]) == {operand_entity("A"), operand_entity("B")}

    def test_acyclic_graph_has_singleton_components(self):
        g = _graph(("A", "B"), ("B", "C"))
        assert all(len(c) == 1 for c in g.sccs())


class TestTopoOrder:
    def test_diamond_respects_dependencies(self):
        g = _graph(("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"))
        order = [comp[0] for comp in g.topo_components()]
        pos = {n: i for i, n in enumerate(order)}
        assert pos[operand_entity("A")] < pos[operand_entity("B")]
        assert pos[operand_entity("A")] < pos[operand_entity("C")]
        assert pos[operand_entity("B")] < pos[operand_entity("D")]
        assert pos[operand_entity("C")] < pos[operand_entity("D")]

    def test_cycle_appears_as_multi_node_component(self):
        g = _graph(("A", "B"), ("B", "A"), ("B", "C"))
        comps = g.topo_components()
        multi = [c for c in comps if len(c) > 1]
        assert len(multi) == 1
        assert set(multi[0]) == {operand_entity("A"), operand_entity("B")}


class TestDigest:
    def test_digest_is_insertion_order_independent(self):
        g1 = _graph(("A", "B"), ("B", "C"))
        g2 = _graph(("B", "C"), ("A", "B"))
        assert g1.digest() == g2.digest()

    def test_digest_changes_with_structure(self):
        g1 = _graph(("A", "B"))
        g2 = _graph(("A", "B"), ("B", "C"))
        assert g1.digest() != g2.digest()

    def test_digest_distinguishes_relation(self):
        g1 = DependencyGraph()
        g1.add_edge(Edge(operand_entity("A"), operand_entity("B"), Relation.FEEDS))
        g2 = DependencyGraph()
        g2.add_edge(Edge(operand_entity("A"), operand_entity("B"), Relation.READS))
        assert g1.digest() != g2.digest()
