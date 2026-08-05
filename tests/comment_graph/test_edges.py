"""Unit tests for typed read/write/feeds edge extraction (Checkpoint 1).

Direction rules mirror ``ModelGenerator._operation`` (:1139) and
``ModelGenerator._OUTPUT_TYPES`` (:1027) in ``src/ladder_renderer/ladder_to_dot.py``.
"""

from ladder_renderer.ladder_to_dot import LadderParser

from comment_graph.model import (
    EntityKind,
    SourceLoc,
    operand_entity,
    rung_entity,
    normalize_operand,
)
from comment_graph.edges import Relation, EdgeExtractor


RUNG = rung_entity("MainProgram", "MainRoutine", 0)
LOC = SourceLoc(program="MainProgram", routine="MainRoutine", rung=0)


def _instr(text: str):
    """Parse a single-instruction rung and return its LadderInstruction."""
    rung = LadderParser().parse_rung(text)
    return rung.main_branch.elements[0]


def _extract(text: str):
    return EdgeExtractor().extract(_instr(text), RUNG, LOC)


def _edges(text: str):
    return _extract(text).edges


def _rel(edges, relation: Relation):
    return [e for e in edges if e.relation is relation]


class TestContactsAndCoils:
    def test_xic_reads_only(self):
        edges = _edges("XIC(Running)")
        reads = _rel(edges, Relation.READS)
        assert [e.dst for e in reads] == [operand_entity("Running")]
        assert _rel(edges, Relation.WRITES) == []

    def test_ote_writes_only(self):
        edges = _edges("OTE(Motor)")
        writes = _rel(edges, Relation.WRITES)
        assert [e.dst for e in writes] == [operand_entity("Motor")]
        assert _rel(edges, Relation.READS) == []


class TestMove:
    def test_mov_reads_source_writes_dest_and_feeds(self):
        edges = _edges("MOV(Source, Dest)")
        assert [e.dst for e in _rel(edges, Relation.READS)] == [operand_entity("Source")]
        assert [e.dst for e in _rel(edges, Relation.WRITES)] == [operand_entity("Dest")]
        feeds = _rel(edges, Relation.FEEDS)
        assert len(feeds) == 1
        assert feeds[0].src == operand_entity("Source")
        assert feeds[0].dst == operand_entity("Dest")


class TestMath:
    def test_add_two_reads_feed_one_write_literal_excluded(self):
        edges = _edges("ADD(N18[1], 1, N101[18])")
        reads = {e.dst for e in _rel(edges, Relation.READS)}
        writes = {e.dst for e in _rel(edges, Relation.WRITES)}
        assert reads == {operand_entity("N18[1]")}  # literal 1 is not an entity
        assert writes == {operand_entity("N101[18]")}
        feeds = _rel(edges, Relation.FEEDS)
        assert len(feeds) == 1
        assert feeds[0].src == operand_entity("N18[1]")
        assert feeds[0].dst == operand_entity("N101[18]")

    def test_cpt_destination_is_first_operand(self):
        edges = _edges("CPT(Dest, Src)")
        assert [e.dst for e in _rel(edges, Relation.WRITES)] == [operand_entity("Dest")]
        assert [e.dst for e in _rel(edges, Relation.READS)] == [operand_entity("Src")]


class TestCompare:
    def test_equ_reads_both_no_write(self):
        edges = _edges("EQU(A, B)")
        assert {e.dst for e in _rel(edges, Relation.READS)} == {
            operand_entity("A"),
            operand_entity("B"),
        }
        assert _rel(edges, Relation.WRITES) == []
        assert _rel(edges, Relation.FEEDS) == []


class TestCopy:
    def test_cop_length_literal_ignored(self):
        edges = _edges("COP(SrcArr, DstArr, 10)")
        assert [e.dst for e in _rel(edges, Relation.READS)] == [operand_entity("SrcArr")]
        assert [e.dst for e in _rel(edges, Relation.WRITES)] == [operand_entity("DstArr")]
        assert len(_rel(edges, Relation.FEEDS)) == 1


class TestTimer:
    def test_ton_writes_timer_tag_only(self):
        edges = _edges("TON(Timer1, 1000, 0)")
        assert [e.dst for e in _rel(edges, Relation.WRITES)] == [operand_entity("Timer1")]
        assert _rel(edges, Relation.READS) == []  # preset/accum are literals


class TestUnsupportedInstruction:
    def test_unknown_instruction_is_unresolved_with_no_directional_edges(self):
        result = _extract("FOOBAR(X, Y)")
        assert result.resolved is False
        # Entity is still retained via REFERENCES edges, but no direction.
        assert _rel(result.edges, Relation.READS) == []
        assert _rel(result.edges, Relation.WRITES) == []
        assert _rel(result.edges, Relation.FEEDS) == []
        refs = _rel(result.edges, Relation.REFERENCES)
        assert {e.dst for e in refs} == {operand_entity("X"), operand_entity("Y")}
        assert all(e.unresolved for e in refs)

    def test_known_instruction_is_resolved(self):
        assert _extract("MOV(A, B)").resolved is True


class TestEdgeMetadata:
    def test_edges_carry_rung_source_and_instruction(self):
        edges = _edges("MOV(A, B)")
        e = edges[0]
        assert e.instruction == "MOV"
        assert e.source_loc.program == "MainProgram"
        assert e.source_loc.rung == 0

    def test_reads_writes_anchored_at_rung(self):
        edges = _edges("MOV(A, B)")
        for e in _rel(edges, Relation.READS) + _rel(edges, Relation.WRITES):
            assert e.src == RUNG
            assert e.src.kind is EntityKind.RUNG
