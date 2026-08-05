"""Typed dependency-edge extraction from ladder instructions.

The read/write direction rules are lifted from the deterministic backbone in
``src/ladder_renderer/ladder_to_dot.py``:

* ``ModelGenerator._operation`` (:1139) encodes the data-flow arrows: MOV
  ``ops0 -> ops1``; ADD/SUB/MUL/DIV ``ops0,ops1 -> ops2``; COP ``ops0 -> ops1``;
  CPT ``ops0 := ops1`` (destination first); compares are read-only.
* ``ModelGenerator._OUTPUT_TYPES`` (:1027) is the destructive-output set
  (COIL/LATCH/UNLATCH, TIMER, COUNTER, RESET, AOI) whose ``ops0`` is written.

Only instructions whose semantics are known here get directional (READS/WRITES/
FEEDS) edges. Everything else keeps its operands as nodes via non-directional
REFERENCES edges flagged ``unresolved`` — no silent direction is ever invented
(see the "No silent edges" risk in the plan).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from ladder_renderer.ladder_to_dot import LadderInstruction, InstructionType

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


# Per-mnemonic operand roles: 'r' = read operand indices, 'w' = write indices.
# Indices out of range or landing on a literal are skipped. FEEDS connects every
# (read operand -> write operand) pair. Sourced from _operation / _OUTPUT_TYPES.
_DIRECTION: Dict[str, Dict[str, List[int]]] = {
    # Contacts (read-only)
    "XIC": {"r": [0]},
    "XIO": {"r": [0]},
    # Coils / destructive single-output
    "OTE": {"w": [0]},
    "OTL": {"w": [0]},
    "OTU": {"w": [0]},
    "RES": {"w": [0]},
    "CLR": {"w": [0]},
    # Timers / counters: instance tag written, preset/accum read
    "TON": {"w": [0], "r": [1, 2]},
    "TOF": {"w": [0], "r": [1, 2]},
    "RTO": {"w": [0], "r": [1, 2]},
    "CTU": {"w": [0], "r": [1, 2]},
    "CTD": {"w": [0], "r": [1, 2]},
    # Compares (read-only). Both short RLL and long neutral-text spellings.
    "EQU": {"r": [0, 1]},
    "NEQ": {"r": [0, 1]},
    "LES": {"r": [0, 1]},
    "LEQ": {"r": [0, 1]},
    "GRT": {"r": [0, 1]},
    "GEQ": {"r": [0, 1]},
    "EQ": {"r": [0, 1]},
    "NE": {"r": [0, 1]},
    "LT": {"r": [0, 1]},
    "LE": {"r": [0, 1]},
    "GT": {"r": [0, 1]},
    "GE": {"r": [0, 1]},
    "LIM": {"r": [0, 1, 2]},
    # Moves. NOTE: the vendored ACD->L5X exporter emits long-form neutral-text
    # mnemonics (MOVE, LT, GT, GE, ...) rather than the short RLL forms, so both
    # spellings are mapped here.
    "MOV": {"r": [0], "w": [1]},
    "MOVE": {"r": [0], "w": [1]},
    "MVM": {"r": [0, 1], "w": [2]},          # source, mask -> dest
    "COP": {"r": [0], "w": [1]},             # ops2 = length (literal), ignored
    "FLL": {"r": [0], "w": [1]},
    # Math: two sources -> destination
    "ADD": {"r": [0, 1], "w": [2]},
    "SUB": {"r": [0, 1], "w": [2]},
    "MUL": {"r": [0, 1], "w": [2]},
    "DIV": {"r": [0, 1], "w": [2]},
    "SQR": {"r": [0], "w": [1]},
    "ABS": {"r": [0], "w": [1]},
    # CPT: destination is the FIRST operand (ops0 := ops1)
    "CPT": {"w": [0], "r": [1]},
}


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

        rule = _DIRECTION.get(mnemonic)
        if rule is None:
            return self._unresolved(ops, rung_id, name, loc, instr.instruction_type)

        def pick(indices: List[int]) -> List[str]:
            picked = []
            for i in indices:
                if i < len(ops) and not is_literal(ops[i]):
                    picked.append(ops[i])
            return picked

        reads = pick(rule.get("r", []))
        writes = pick(rule.get("w", []))

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
        instructions (JSR, ONS, motion, ...). We never infer AOI parameter
        direction.
        """
        edges = [
            Edge(rung_id, operand_entity(o), Relation.REFERENCES,
                 confidence=Confidence.LOW, source_loc=loc, instruction=name,
                 unresolved=True)
            for o in ops
            if not is_literal(o)
        ]
        return ExtractResult(edges=edges, resolved=False)
