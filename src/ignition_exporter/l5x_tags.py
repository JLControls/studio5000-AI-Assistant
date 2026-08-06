#!/usr/bin/env python3
"""Shared L5X tag-DB loader and signal-flow index for the Ignition exporter.

This is the single place the Ignition tools read a Studio 5000 project's tag
database. It reuses :class:`tag_analyzer.comment_pipeline.PLCCommentPipeline`
for ACD/L5X resolution and BOM-safe parsing so behavior matches the rest of the
repo, and adds two things the existing scanner omits:

* ``external_access`` per tag (needed to exclude ``ExternalAccess="None"`` tags
  that cannot be read over OPC UA), and
* decorated ``DataValueMember`` values (needed by the analog-scaling detector to
  read a scaling block's real ``InputMin/InputMax/ScaledMin/ScaledMax`` member
  values rather than assuming standard raw ranges).

It also builds a light signal-flow index: for every rung it records the
instruction calls and their operands so the scaling detector can trace which tag
feeds a block's ``.Input`` and which consumes its ``.Output``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

from tag_analyzer.comment_pipeline import PLCCommentPipeline

# Instruction-call shape, mirroring PLCCommentPipeline.parse_rung_structure's
# ``instr_pattern`` -- MNEMONIC(op, op, ...). Operands are captured raw and split
# on top-level commas by :func:`split_operands` (nested [..] indices are kept).
INSTR_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")


@dataclass
class TagEntry:
    """One PLC tag as seen in the L5X, with the fields the Ignition tools need."""

    name: str
    scope: str  # "Controller" or the program name
    program: str  # "" for controller scope
    data_type: str
    alias_for: str = ""
    comment: str = ""
    external_access: str = "Read/Write"
    # Decorated struct member values, keyed by member name (e.g. "InputMin").
    # Empty for atomic tags. Values are kept as their raw string form; callers
    # coerce to float where a number is expected.
    members: Dict[str, str] = field(default_factory=dict)
    # Decorated scalar value for an atomic tag (e.g. a scale-range setpoint's
    # value). None when the tag is a struct or has no populated value.
    value: Optional[str] = None


@dataclass
class RungRef:
    """A single instruction call inside a rung, retained for signal-flow tracing."""

    routine: str
    program: str
    rung_number: int
    instruction: str
    operands: List[str]
    text: str


def split_operands(operand_str: str) -> List[str]:
    """Split an instruction's operand string on top-level commas.

    Commas inside array subscripts (``Foo[1,2]``) or nested parens are ignored so
    ``SCP(In,0,27648,0,60,Out)`` yields six operands and ``Foo[Bar.Idx]`` stays whole.
    """
    operands: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in operand_str:
        if ch in "[(":
            depth += 1
            current.append(ch)
        elif ch in "])":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            operands.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        operands.append(tail)
    return operands


class IgnitionTagDB:
    """In-memory view of an L5X tag database plus a signal-flow (rung) index."""

    def __init__(self, l5x_path: Path, controller_name: str):
        self.l5x_path = l5x_path
        self.controller_name = controller_name
        self.tags: Dict[str, TagEntry] = {}
        # Ordered rung index for signal-flow tracing.
        self.rungs: List[RungRef] = []

    # -- lookups -----------------------------------------------------------
    def get(self, name: str) -> Optional[TagEntry]:
        """Look up a tag by its base name (strips any ``.member`` suffix)."""
        return self.tags.get(name.split(".")[0])

    def is_accessible(self, name: str) -> bool:
        """True unless the tag exists and is explicitly ``ExternalAccess="None"``."""
        entry = self.get(name)
        return not (entry is not None and entry.external_access == "None")

    def opc_addressable_tags(self) -> List[TagEntry]:
        """Every tag that can be read over OPC UA (excludes ``ExternalAccess="None"``)."""
        return [t for t in self.tags.values() if t.external_access != "None"]

    def calls_with_operand(self, tag_name: str) -> List[RungRef]:
        """Rung instruction calls that reference ``tag_name`` in any operand.

        Matches on the base tag name, so ``Blk.Output`` and ``Blk`` both match a
        call that mentions ``Blk``.
        """
        base = tag_name.split(".")[0]
        hits: List[RungRef] = []
        for rung in self.rungs:
            for op in rung.operands:
                if op.split(".")[0].split("[")[0] == base:
                    hits.append(rung)
                    break
        return hits


def _member_values(tag_elem: ET.Element) -> Dict[str, str]:
    """Extract decorated ``DataValueMember`` name->value pairs from a <Tag>.

    Handles the common decorated form::

        <Data Format="Decorated">
          <Structure DataType="SCPLim1">
            <DataValueMember Name="InputMin" Value="0"/>
            ...

    Nested structures are flattened; the last-seen value for a member name wins,
    which is sufficient for the flat AOI/UDT scaling instances this targets.
    """
    members: Dict[str, str] = {}
    for data in tag_elem.findall("Data"):
        if data.attrib.get("Format") != "Decorated":
            continue
        for dvm in data.iter("DataValueMember"):
            name = dvm.attrib.get("Name")
            if name is not None:
                members[name] = dvm.attrib.get("Value", "")
    return members


def _scalar_value(tag_elem: ET.Element) -> Optional[str]:
    """Extract an atomic tag's decorated scalar value (``<DataValue Value=.../>``)."""
    for data in tag_elem.findall("Data"):
        if data.attrib.get("Format") != "Decorated":
            continue
        dv = data.find("DataValue")
        if dv is not None and "Value" in dv.attrib:
            return dv.attrib.get("Value")
    return None


def _process_tags_node(tags_node: ET.Element, scope: str, program: str,
                       tags: Dict[str, TagEntry]) -> None:
    """Populate ``tags`` from a <Tags> container (controller or program scope)."""
    for tag in tags_node.findall("Tag"):
        name = tag.attrib.get("Name", "")
        if not name:
            continue
        comment_elem = tag.find("Comment")
        comment = comment_elem.text.strip() if (comment_elem is not None and comment_elem.text) else ""
        tags[name] = TagEntry(
            name=name,
            scope=scope,
            program=program,
            data_type=tag.attrib.get("DataType", ""),
            alias_for=tag.attrib.get("AliasFor", ""),
            comment=comment,
            external_access=tag.attrib.get("ExternalAccess", "Read/Write"),
            members=_member_values(tag),
            value=_scalar_value(tag),
        )


def _index_rungs(root: ET.Element, db: IgnitionTagDB) -> None:
    """Walk every routine's rungs and record instruction calls for flow tracing."""
    for program in root.findall(".//Programs/Program"):
        prog_name = program.attrib.get("Name", "")
        for routine in program.findall(".//Routines/Routine"):
            rout_name = routine.attrib.get("Name", "")
            for rung in routine.findall(".//Rung"):
                try:
                    rung_num = int(rung.attrib.get("Number", "0"))
                except ValueError:
                    rung_num = 0
                text_elem = rung.find("Text")
                text = text_elem.text if (text_elem is not None and text_elem.text) else ""
                if not text:
                    continue
                for instr, operand_str in INSTR_CALL_RE.findall(text):
                    db.rungs.append(RungRef(
                        routine=rout_name,
                        program=prog_name,
                        rung_number=rung_num,
                        instruction=instr,
                        operands=split_operands(operand_str),
                        text=text.strip(),
                    ))


def load_tag_db(file_path: str | Path) -> IgnitionTagDB:
    """Load a Studio 5000 project (``.ACD`` or ``.L5X``) into an :class:`IgnitionTagDB`.

    ACD files are resolved/converted to L5X via
    :meth:`PLCCommentPipeline.resolve_l5x_path`. Both controller-scope
    (``Controller/Tags/Tag``) and program-scope (``Programs/Program/Tags/Tag``)
    tags are loaded, including decorated member values and ``ExternalAccess``.
    """
    l5x_path = PLCCommentPipeline.resolve_l5x_path(file_path)
    root = PLCCommentPipeline.parse_l5x_tree(l5x_path)

    controller = root.find("Controller")
    controller_name = controller.attrib.get("Name", "Controller") if controller is not None else "Controller"
    db = IgnitionTagDB(l5x_path=l5x_path, controller_name=controller_name)

    ctrl_tags = root.find(".//Controller/Tags")
    if ctrl_tags is not None:
        _process_tags_node(ctrl_tags, "Controller", "", db.tags)

    for program in root.findall(".//Programs/Program"):
        prog_name = program.attrib.get("Name", "")
        prog_tags = program.find("Tags")
        if prog_tags is not None:
            _process_tags_node(prog_tags, prog_name, prog_name, db.tags)

    _index_rungs(root, db)
    return db
