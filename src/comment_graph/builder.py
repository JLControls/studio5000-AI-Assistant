"""Build a typed dependency graph from an L5X (or ACD) source.

Reuses existing parsers rather than reinventing them:

* ``inventory_l5x`` (``src/l5x_analyzer/l5x_semantic_validation.py`` :52) for the
  semantic maps (rungs, rung/operand comments, modules, descriptions, tags).
* ``LadderParser`` (``src/ladder_renderer/ladder_to_dot.py`` :111) to parse each
  rung's text into instructions (including nested branches).
* ``convert_acd_to_l5x`` (``src/l5x_analyzer/acd_offline_convert.py`` :41) for the
  ACD path; its ``note``/``validation`` provenance is carried forward.
* ``COMMON_INSTRUCTIONS`` (``src/verification/sdk_verifier.py`` :16) so the
  ``unresolved_instruction`` warning vocabulary matches the existing verifier.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ladder_renderer.ladder_to_dot import (
    LadderParser,
    LadderInstruction,
    LadderBranch,
    LadderBranchGroup,
)
from l5x_analyzer.l5x_semantic_validation import inventory_l5x
from l5x_analyzer.acd_offline_convert import convert_acd_to_l5x
from verification.sdk_verifier import COMMON_INSTRUCTIONS

from .model import (
    EntityId,
    SourceLoc,
    base_tag_of,
    operand_entity,
    rung_entity,
    tag_entity,
)
from .edges import Edge, Relation, EdgeExtractor
from .graph_adapter import DependencyGraph


@dataclass(frozen=True)
class RungInfo:
    """Per-rung context used later for fact seeding and worker snapshots."""

    program: str
    routine: str
    number: str
    text: str
    comment: str = ""


@dataclass
class BuildResult:
    graph: DependencyGraph
    provenance: Dict[str, object]
    warnings: List[str] = field(default_factory=list)
    inventory: Dict[str, Dict] = field(default_factory=dict)
    rungs: Dict[EntityId, RungInfo] = field(default_factory=dict)


def _iter_instructions(branch: LadderBranch):
    """Yield every LadderInstruction in a branch, descending into branch groups."""
    for element in branch.elements:
        if isinstance(element, LadderInstruction):
            yield element
        elif isinstance(element, LadderBranchGroup):
            for sub in element.branches:
                yield from _iter_instructions(sub)


class ModelBuilder:
    """Resolve/parse a source and construct ``(DependencyGraph, provenance)``."""

    def __init__(self) -> None:
        self._parser = LadderParser()
        self._extractor = EdgeExtractor()

    def build(self, source_path: str | Path) -> BuildResult:
        source_path = Path(source_path)
        resolved, provenance = self._resolve(source_path)

        inventory = inventory_l5x(resolved)
        graph = DependencyGraph()
        warnings: List[str] = []
        rungs: Dict[EntityId, RungInfo] = {}

        for (program, routine, number), text in sorted(inventory["rungs"].items()):
            rid = rung_entity(program, routine, number)
            graph.add_entity(rid)
            comment = inventory["rung_comments"].get((program, routine, number), "")
            rungs[rid] = RungInfo(program, routine, number, text, comment)
            loc = SourceLoc(
                program=program,
                routine=routine,
                rung=int(number) if str(number).lstrip("-").isdigit() else None,
            )
            self._process_rung(text, rid, loc, graph, warnings)

        provenance["graph_digest"] = graph.digest()
        return BuildResult(
            graph=graph,
            provenance=provenance,
            warnings=warnings,
            inventory=inventory,
            rungs=rungs,
        )

    # -- internals --------------------------------------------------------
    def _resolve(self, source_path: Path):
        """Return (resolved_l5x_path, provenance). Converts ACD when needed."""
        provenance: Dict[str, object] = {"source_path": str(source_path)}
        if source_path.suffix.lower() == ".acd":
            out = Path(tempfile.mkdtemp(prefix="comment_graph_")) / (source_path.stem + ".L5X")
            conversion = convert_acd_to_l5x(source_path, out)
            if not conversion.get("success"):
                raise ValueError(f"ACD conversion failed: {conversion.get('error')}")
            provenance["source_kind"] = "converted_acd"
            provenance["resolved_l5x_path"] = str(out)
            provenance["conversion_warnings"] = {
                "note": conversion.get("note"),
                "validation": conversion.get("validation"),
                "acd_source": conversion.get("acd_source"),
            }
            resolved = out
        else:
            provenance["source_kind"] = "native_l5x"
            provenance["resolved_l5x_path"] = str(source_path)
            resolved = source_path

        provenance["source_artifact_hash"] = hashlib.sha256(
            resolved.read_bytes()
        ).hexdigest()
        return resolved, provenance

    def _process_rung(
        self,
        text: str,
        rid: EntityId,
        loc: SourceLoc,
        graph: DependencyGraph,
        warnings: List[str],
    ) -> None:
        rung = self._parser.parse_rung(text)
        for instr in _iter_instructions(rung.main_branch):
            if instr.instruction.upper() == "NOP":
                continue
            result = self._extractor.extract(instr, rid, loc)
            for edge in result.edges:
                graph.add_edge(edge)
                self._link_base_tag(edge, graph)
            if not result.resolved:
                warnings.append(
                    self._unresolved_warning(instr, loc)
                )

    def _link_base_tag(self, edge: Edge, graph: DependencyGraph) -> None:
        """Add an operand -> base-tag REFERENCES edge so tag facts flow to members.

        Applies even to scalar operands (``op:A`` -> ``tag:A``): the operand and
        its tag are distinct nodes, so a tag-level comment/description must have
        an edge to reach the operand that carries it into the logic.
        """
        for endpoint in (edge.src, edge.dst):
            if endpoint.kind.value != "op":
                continue
            base = base_tag_of(endpoint.key)
            if base:
                graph.add_edge(
                    Edge(endpoint, tag_entity(base), Relation.REFERENCES)
                )

    def _unresolved_warning(self, instr: LadderInstruction, loc: SourceLoc) -> str:
        mnemonic = instr.instruction.upper()
        known = mnemonic in COMMON_INSTRUCTIONS
        kind = "no direction rule" if known else "unknown instruction"
        where = f"{loc.program}/{loc.routine} rung {loc.rung}"
        return f"unresolved_instruction: {instr.instruction} ({kind}) at {where}"
