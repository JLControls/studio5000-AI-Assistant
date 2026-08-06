#!/usr/bin/env python3
"""Candidate Ignition folder-tree generators (tool #5).

Synthesizes 2-3 project-agnostic hierarchy options from a project's tags. The
same grouping functions back ``generate_ignition_tags`` (tool #2) via
``folder_hierarchy_model`` so a proposed tree and a generated tree agree.

Three models:
  * **PhysicalSubsystem** -- group by process area inferred from name segmentation.
  * **EquipmentClass**    -- group by device class (function + analog/digital role).
  * **AreaLocation**      -- group by module/panel from the tag's I/O address.
"""

from __future__ import annotations

import re
from typing import Dict, List

from tag_analyzer.tag_chunk import (
    detect_function_from_description,
    extract_device_info_from_address,
)

from .l5x_tags import IgnitionTagDB, TagEntry, load_tag_db

VALID_MODELS = ("PhysicalSubsystem", "EquipmentClass", "AreaLocation")

# Generic Rockwell-style role/scope segments to strip when inferring a subsystem
# from a tag name. These are naming *conventions*, not project-specific names.
_ROLE_PREFIX_SEGMENTS = {
    "com", "cmd", "set", "d", "raw", "alias", "aliasain", "aliasdin",
    "aliasaout", "aliasdout", "ain", "aout", "din", "dout", "sc", "alm",
}

_UNGROUPED = "Ungrouped"


def _segments(name: str) -> List[str]:
    return [s for s in re.split(r"[_\s]+", name) if s]


def _subsystem_of(name: str) -> str:
    """Infer a physical-subsystem label by dropping leading role/scope segments."""
    segs = _segments(name)
    for seg in segs:
        if seg.lower() not in _ROLE_PREFIX_SEGMENTS:
            return seg
    return segs[0] if segs else _UNGROUPED


def _role_of(name: str) -> str:
    """Coarse analog/digital in/out role from generic name tokens."""
    low = name.lower()
    if any(t in low for t in ("aliasain", "ain", "anlgin")):
        return "Analog Inputs"
    if any(t in low for t in ("aliasaout", "aout", "anlgout")):
        return "Analog Outputs"
    if any(t in low for t in ("aliasdout", "dout")):
        return "Digital Outputs"
    if any(t in low for t in ("aliasdin", "din")):
        return "Digital Inputs"
    return "Other"


def group_physical_subsystem(tags: List[TagEntry]) -> Dict[str, List[str]]:
    grouping: Dict[str, List[str]] = {}
    for t in tags:
        grouping.setdefault(_subsystem_of(t.name), []).append(t.name)
    return grouping


def group_equipment_class(tags: List[TagEntry]) -> Dict[str, List[str]]:
    grouping: Dict[str, List[str]] = {}
    for t in tags:
        func = detect_function_from_description(t.comment, t.name)
        role = _role_of(t.name)
        label = f"{role}/{func}" if func else role
        grouping.setdefault(label, []).append(t.name)
    return grouping


def group_area_location(tags: List[TagEntry]) -> Dict[str, List[str]]:
    grouping: Dict[str, List[str]] = {}
    for t in tags:
        info = extract_device_info_from_address(t.name, t.data_type, t.comment)
        label = info.module_type or info.device_category or (t.program or "Controller")
        grouping.setdefault(label, []).append(t.name)
    return grouping


_MODEL_FUNCS = {
    "PhysicalSubsystem": group_physical_subsystem,
    "EquipmentClass": group_equipment_class,
    "AreaLocation": group_area_location,
}

_MODEL_RATIONALE = {
    "PhysicalSubsystem": "Group tags by the process area inferred from tag-name segmentation.",
    "EquipmentClass": "Group tags by device class (function plus analog/digital I/O role).",
    "AreaLocation": "Group tags by physical module/panel from the tag's I/O address.",
}


def build_folder_grouping(tags: List[TagEntry], model: str) -> Dict[str, List[str]]:
    """Grouping (folder label -> tag names) for a model. Shared with the generator."""
    func = _MODEL_FUNCS.get(model)
    if func is None:
        raise ValueError(f"Unknown folder_hierarchy_model: {model!r}. "
                         f"Valid: {', '.join(VALID_MODELS)}")
    return func(tags)


def _to_skeleton(grouping: Dict[str, List[str]]) -> Dict[str, object]:
    """Turn a flat ``label -> names`` map (labels may nest via '/') into a tree."""
    root: Dict[str, object] = {}
    for label, names in sorted(grouping.items()):
        node = root
        for part in label.split("/"):
            node = node.setdefault(part, {})  # type: ignore[assignment]
        node["_tags"] = sorted(names)  # type: ignore[index]
    return root


def propose_folder_structures(file_path: str, max_options: int = 3) -> Dict[str, object]:
    """Propose up to ``max_options`` candidate folder trees for a project (tool #5)."""
    db = load_tag_db(file_path)
    tags = db.opc_addressable_tags()

    options = []
    for model in VALID_MODELS[:max(1, max_options)]:
        grouping = build_folder_grouping(tags, model)
        options.append({
            "model": model,
            "rationale": _MODEL_RATIONALE[model],
            "folder_count": len(grouping),
            "folder_tree": _to_skeleton(grouping),
        })

    return {
        "success": True,
        "project_name": db.controller_name,
        "tag_count": len(tags),
        "options": options,
    }
