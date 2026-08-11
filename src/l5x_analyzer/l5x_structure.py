"""Deterministic structural parsing of exported L5X files.

This module walks the L5X XML tree to enumerate the controller's programs,
routines, and user-defined data types. It is the authoritative source of
project structure for :func:`get_project_overview`, replacing the previous
approach that derived counts from a recall-limited semantic search
(see issue #9).

Routines are keyed by ``(program, routine)`` so that same-named routines in
different programs are counted independently, and encrypted routines exported
as ``<EncodedData EncodedType="Routine">`` are counted alongside plain
``<Routine>`` elements so encrypted logic is never silently dropped.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def _empty_structure() -> Dict[str, Any]:
    return {"controller": None, "programs": [], "routines": [], "udts": []}


def parse_l5x_structure(l5x_path: str | Path) -> Dict[str, Any]:
    """Parse an exported L5X file into a deterministic structure dictionary.

    Returns a dict with keys:

    - ``controller``: the controller name (or ``None`` if absent).
    - ``programs``: list of program names in document order.
    - ``routines``: list of ``{program, name, type, encoded}`` dicts.
    - ``udts``: list of user-defined data type names.

    A parse failure is logged and yields an empty structure rather than raising,
    so a single malformed file cannot abort indexing of an entire project.
    """
    structure = _empty_structure()

    try:
        tree = ET.parse(str(l5x_path))
        root = tree.getroot()
    except Exception as exc:  # malformed XML, missing file, etc.
        logger.error("Failed to structurally parse L5X %s: %s", l5x_path, exc)
        return structure

    controller = root.find(".//Controller")
    if controller is not None:
        structure["controller"] = controller.get("Name")

    for program in root.findall(".//Programs/Program"):
        program_name = program.get("Name", "Unknown")
        structure["programs"].append(program_name)

        routines_parent = program.find("Routines")
        if routines_parent is None:
            continue

        for routine in routines_parent.findall("Routine"):
            structure["routines"].append({
                "program": program_name,
                "name": routine.get("Name", "Unknown"),
                "type": routine.get("Type", "RLL"),
                "encoded": False,
            })

        # Encrypted routines export as EncodedData rather than Routine; count
        # them too so encrypted logic is not silently dropped from the overview.
        for encoded in routines_parent.findall("EncodedData"):
            if encoded.get("EncodedType") != "Routine":
                continue
            structure["routines"].append({
                "program": program_name,
                "name": encoded.get("Name", "Unknown"),
                "type": encoded.get("Type", "RLL"),
                "encoded": True,
            })

    for data_type in root.findall(".//DataTypes/DataType[@Class='User']"):
        structure["udts"].append(data_type.get("Name", "Unknown"))

    return structure


def merge_structures(structures: Iterable[Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """Merge several per-file structures into one deterministic project structure.

    Programs are unioned by name, routines by ``(program, routine)``, and UDTs by
    name, all preserving first-seen order. ``None`` entries (from failed parses)
    are skipped.
    """
    programs: "dict[str, None]" = {}
    routines: "dict[tuple, Dict[str, Any]]" = {}
    udts: "dict[str, None]" = {}
    controller: Optional[str] = None

    for structure in structures:
        if not structure:
            continue
        if controller is None and structure.get("controller"):
            controller = structure["controller"]
        for program_name in structure.get("programs", []):
            programs.setdefault(program_name, None)
        for routine in structure.get("routines", []):
            key = (routine.get("program"), routine.get("name"))
            routines.setdefault(key, routine)
        for udt_name in structure.get("udts", []):
            udts.setdefault(udt_name, None)

    return {
        "controller": controller,
        "programs": list(programs.keys()),
        "routines": list(routines.values()),
        "udts": list(udts.keys()),
    }


def summarize_structure(structure: Dict[str, Any]) -> Dict[str, int]:
    """Return ``program_count`` / ``routine_count`` / ``udt_count`` for a structure."""
    return {
        "program_count": len(structure.get("programs", [])),
        "routine_count": len(structure.get("routines", [])),
        "udt_count": len(structure.get("udts", [])),
    }
