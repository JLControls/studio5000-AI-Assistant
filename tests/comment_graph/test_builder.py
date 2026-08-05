"""Unit tests for ModelBuilder (Checkpoint 2), driven by synthetic L5X."""

from comment_graph.model import operand_entity, tag_entity, rung_entity
from comment_graph.edges import Relation
from comment_graph.builder import ModelBuilder

from tests.comment_graph.conftest import rung_xml, tag_xml


def _rel(edges, relation):
    return [e for e in edges if e.relation is relation]


class TestGraphConstruction:
    def test_math_rung_creates_operands_and_feeds(self, l5x_factory):
        path = l5x_factory(rungs_xml=rung_xml(0, "ADD(N18[1],1,N101[18]);"))
        result = ModelBuilder().build(path)
        g = result.graph

        assert g.has_node(operand_entity("N18[1]"))
        assert g.has_node(operand_entity("N101[18]"))
        feeds = _rel(g.edges(), Relation.FEEDS)
        assert any(
            e.src == operand_entity("N18[1]") and e.dst == operand_entity("N101[18]")
            for e in feeds
        )

    def test_rung_entity_created(self, l5x_factory):
        path = l5x_factory(rungs_xml=rung_xml(0, "MOV(A,B);"))
        result = ModelBuilder().build(path)
        assert result.graph.has_node(rung_entity("MainProgram", "MainRoutine", 0))

    def test_operand_references_base_tag(self, l5x_factory):
        path = l5x_factory(rungs_xml=rung_xml(0, "ADD(N18[1],1,N101[18]);"))
        result = ModelBuilder().build(path)
        refs = _rel(result.graph.edges(), Relation.REFERENCES)
        assert any(
            e.src == operand_entity("N101[18]") and e.dst == tag_entity("N101")
            for e in refs
        )

    def test_instructions_inside_branches_are_extracted(self, l5x_factory):
        # Parallel branch: two contacts feeding one coil.
        path = l5x_factory(rungs_xml=rung_xml(0, "[XIC(A),XIC(B)]OTE(C);"))
        result = ModelBuilder().build(path)
        g = result.graph
        assert g.has_node(operand_entity("A"))
        assert g.has_node(operand_entity("B"))
        assert g.has_node(operand_entity("C"))
        writes = _rel(g.edges(), Relation.WRITES)
        assert any(e.dst == operand_entity("C") for e in writes)


class TestUnresolvedInstructions:
    def test_unknown_instruction_warns_and_retains_entity(self, l5x_factory):
        path = l5x_factory(rungs_xml=rung_xml(0, "FOOBAR(X,Y);"))
        result = ModelBuilder().build(path)
        # Entities retained
        assert result.graph.has_node(operand_entity("X"))
        # No directional edge invented
        assert _rel(result.graph.edges(), Relation.FEEDS) == []
        # Warning surfaced, naming the instruction
        assert any("FOOBAR" in w for w in result.warnings)


class TestProvenance:
    def test_native_l5x_provenance(self, l5x_factory):
        path = l5x_factory(rungs_xml=rung_xml(0, "MOV(A,B);"))
        result = ModelBuilder().build(path)
        prov = result.provenance
        assert prov["source_kind"] == "native_l5x"
        assert prov["source_artifact_hash"]
        assert prov["graph_digest"] == result.graph.digest()

    def test_source_artifact_hash_tracks_bytes(self, l5x_factory):
        p1 = l5x_factory(rungs_xml=rung_xml(0, "MOV(A,B);"))
        p2 = l5x_factory(rungs_xml=rung_xml(0, "MOV(A,C);"))
        h1 = ModelBuilder().build(p1).provenance["source_artifact_hash"]
        h2 = ModelBuilder().build(p2).provenance["source_artifact_hash"]
        assert h1 != h2


class TestInventoryForSeeding:
    def test_operand_comments_available(self, l5x_factory):
        path = l5x_factory(
            tags_xml=tag_xml("N101", operand_comments={"[18]": "calibrated temperature"}),
            rungs_xml=rung_xml(0, "ADD(N18[1],1,N101[18]);"),
        )
        result = ModelBuilder().build(path)
        assert result.inventory["operand_comments"][("N101", "[18]")] == "calibrated temperature"

    def test_rungs_mapped_by_entity(self, l5x_factory):
        path = l5x_factory(rungs_xml=rung_xml(0, "MOV(A,B);", comment="seed comment"))
        result = ModelBuilder().build(path)
        rid = rung_entity("MainProgram", "MainRoutine", 0)
        assert rid in result.rungs
        assert result.rungs[rid].comment == "seed comment"
        assert "MOV(A,B)" in result.rungs[rid].text
