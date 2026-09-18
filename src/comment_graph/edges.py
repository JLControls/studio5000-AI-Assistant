"""Typed dependency-edge extraction from ladder instructions.

Operand direction comes from ``src/plc_instruction_semantics.py``. Only
instructions with a shared directional entry get READS/WRITES/FEEDS edges;
known-but-undirected and unknown instructions retain non-directional
REFERENCES edges flagged ``unresolved`` so no direction is invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from ladder_renderer.ladder_to_dot import LadderInstruction, InstructionType
from plc_instruction_semantics import get_operand_indices, is_known_instruction

from .model import (
    Confidence,
    EntityId,
    SourceLoc,
    is_literal,
    normalize_operand,
    operand_entity,
)


class Relation(Enum):
    """Edge relation types between graph nodes."""

    READS = "reads"                    # rung -> operand it reads
    WRITES = "writes"                  # rung -> operand it writes (destructive)
    FEEDS = "feeds"                    # source operand -> destination operand
    ALIAS_OF = "alias_of"              # operand/tag -> its alias target
    CONTAINS = "contains"              # container -> member (rung -> operand)
    REFERENCES = "references"          # operand -> base tag, or unresolved use
    COMMENT_EVIDENCE = "comment_evidence"  # operand -> the comment that describes it


@dataclass(frozen=True)
class Edge:
    """A typed, directed dependency edge."""

    src: EntityId
    dst: EntityId
    relation: Relation
    confidence: Confidence = Confidence.HIGH
    source_loc: Optional[SourceLoc] = None
    instruction: str = ""
    unresolved: bool = False
    evidence_id: Optional[str] = None


@dataclass
class ExtractResult:
    """Edges produced for one instruction plus whether direction was known."""

    edges: List[Edge] = field(default_factory=list)
    resolved: bool = True


class EdgeExtractor:
    """Turns a parsed ladder instruction into typed dependency edges."""

    def extract(
        self,
        instr: LadderInstruction,
        rung_id: EntityId,
        source_loc: Optional[SourceLoc] = None,
    ) -> ExtractResult:
        name = instr.instruction
        mnemonic = name.upper()
        loc = source_loc or SourceLoc()
        ops = [normalize_operand(o) for o in instr.operands]

        read_indices, write_indices, control_indices = get_operand_indices(
            mnemonic, len(ops)
        )
        if not is_known_instruction(mnemonic) or not (
            read_indices or write_indices or control_indices
        ):
            return self._unresolved(ops, rung_id, name, loc, instr.instruction_type)

        def pick(indices: List[int]) -> List[str]:
            picked = []
            for i in indices:
                if i < len(ops) and not is_literal(ops[i]):
                    picked.append(ops[i])
            return picked

        reads = pick(list(read_indices))
        # Control operands mutate state but are not treated as data sources in
        # the graph, avoiding a meaningless self FEEDS edge for ONS/TON.
        writes = pick(list(write_indices) + list(control_indices))

        edges: List[Edge] = []
        for operand in reads:
            edges.append(
                Edge(rung_id, operand_entity(operand), Relation.READS,
                     source_loc=loc, instruction=name)
            )
        for operand in writes:
            edges.append(
                Edge(rung_id, operand_entity(operand), Relation.WRITES,
                     source_loc=loc, instruction=name)
            )
        for w in writes:
            for r in reads:
                edges.append(
                    Edge(operand_entity(r), operand_entity(w), Relation.FEEDS,
                         source_loc=loc, instruction=name)
                )
        return ExtractResult(edges=edges, resolved=True)

    def _unresolved(
        self,
        ops: List[str],
        rung_id: EntityId,
        name: str,
        loc: SourceLoc,
        instr_type: InstructionType,
    ) -> ExtractResult:
        """No known direction: keep operands as nodes, flag them unresolved.

        Applies to unknown mnemonics and to AOI calls / known-but-undirected
        instructions (motion, message, and other instructions without a safe
        generic operand rule). We never infer AOI parameter direction.
        """
        edges = [
            Edge(rung_id, operand_entity(o), Relation.REFERENCES,
                 confidence=Confidence.LOW, source_loc=loc, instruction=name,
                 unresolved=True)
            for o in ops
            if not is_literal(o)
        ]
        return ExtractResult(edges=edges, resolved=False)
