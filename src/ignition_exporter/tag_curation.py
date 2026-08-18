#!/usr/bin/env python3
"""Tag categorization and curation for Ignition export selection.

A generalized L5X exposes far more tags than belong in a SCADA import: drive-comms
structs, scaling-AOI internals, configurators, scratch/diagnostic bits, etc. Dumping
all of them buries the operator-facing process tags.

This module classifies every tag into a category and marks the operator-facing ones
(analog PVs, setpoints, alarms, field I/O status, commands) as *recommended*. It
backs a dialog workflow: ``list_ignition_tag_candidates`` presents the full,
categorized inventory so the calling agent can make judgement calls (and ask the
user when unsure) before telling ``generate_ignition_tags`` what to build. The same
recommendation drives the curated default when no explicit selection is given.

Category rules use common Rockwell naming *conventions* (Alias/Set/Comms/Cnfg...),
never project-specific tag names, and every candidate carries a human-readable
``reason`` so the agent can override the heuristic.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from tag_analyzer.tag_chunk import detect_function_from_description
from l5x_analyzer.write_analyzer import TagWriteMap, analyze_l5x_tag_writes
from l5x_analyzer.ambiguity_detector import detect_tag_ambiguities

from .analog_scaling import _has_scaling_signature, _normalize_members
from .aoi_structure_parser import is_expandable_structure, expand_structure_members
from .historian_rules import classify_signal_type
from .l5x_tags import IgnitionTagDB, TagEntry, load_tag_db


# Operator-facing categories included in the curated "key process metrics" default.
KEY_CATEGORIES = frozenset({
    "analog_pv", "setpoint", "alarm", "status", "command", "field_io",
})
# Categories excluded from the curated default (still listed for the agent).
NOISE_CATEGORIES = frozenset({"comms", "config", "internal", "other"})

# Physical-field naming tokens. A tag carrying one of these is a real device point
# (an aliased channel / motor aux / E-Stop), so it stays relevant even when the
# write-detection engine finds no logic writing it (it is driven by the wire).
_FIELD_TOKENS = frozenset({"din", "dout", "ain", "aout", "aux", "estop"})


def build_write_map(file_path) -> Optional[TagWriteMap]:
    """Parse an L5X and build its tag write-map, or None if it can't be analyzed.

    Shared by the discovery inventory and the generation default so both apply the
    same relevance discriminator (BUG-007). ``file_path`` should be a resolved
    ``.L5X`` (pass ``IgnitionTagDB.l5x_path``); non-XML inputs return None.
    """
    try:
        tree = ET.parse(str(file_path))
        return analyze_l5x_tag_writes(tree.getroot())
    except Exception:
        return None


def _tokens(name: str) -> List[str]:
    return [t for t in re.split(r"[_\s]+", name) if t]


def _has(name: str, *needles: str) -> bool:
    low = name.lower()
    return any(n in low for n in needles)


def _is_scaling_instance(entry: TagEntry) -> bool:
    return bool(entry.members) and _has_scaling_signature(_normalize_members(entry.members))


def classify_category(entry: TagEntry) -> str:
    """Classify a tag into a curation category (see module docstring)."""
    name = entry.name
    tokens = {t.lower() for t in _tokens(name)}
    dt = entry.data_type.upper()

    # --- noise first, so it is never mistaken for a key signal --------------
    # Communications structures/blocks (NOT the leading "Com_" common scope).
    if "comms" in tokens or "comm" in tokens or _has(name, "danfoss", "modbus", "_msg", "heartbeat", "ethernet"):
        return "comms"
    # Scaling-AOI instances and their wiring scratch, PID/loop instances, etc.
    if _is_scaling_instance(entry) or dt in ("SCP", "SCPLIM1", "PID", "PIDE"):
        return "internal"
    if tokens & {"scp1", "data1", "wdata1", "lim1", "lim2"}:
        return "internal"
    # Configurators, buffers, clocks, calendars, scratch/diagnostic.
    if tokens & {"cnfg", "config", "configurator", "configurator1", "configurator2",
                 "buf", "buffer", "clock", "day", "date", "scratch", "spare",
                 "test", "diag", "debug", "sim", "temp1", "tmp",
                 "placeholder", "holder", "future", "unused", "reserved"}:
        return "config"

    # --- key, operator-facing categories -----------------------------------
    if _has(name, "alarm", "_alm", "fault", "_flt", "_fail", "estop", "e_stop"):
        return "alarm"
    if "set" in tokens or _has(name, "setpoint", "_sc", "_sp"):
        return "setpoint"
    # Physical field I/O aliases (analog/digital in/out) -- the points on the wire.
    if re.search(r"Alias(?:A|D)(?:In|Out)", name) or tokens & {"aliasain", "aliasdin", "aliasaout", "aliasdout"}:
        return "field_io"
    if _has(name, "cmd", "command") or "cmd" in tokens:
        return "command"
    if dt in ("REAL", "LREAL"):
        sig = classify_signal_type(tag_name=name, description=entry.comment)
        if sig in ("pressure", "temperature", "level", "flow", "speed", "energy"):
            return "analog_pv"
    if dt in ("BOOL",) and (tokens & {"auto", "aux", "disc", "run", "running", "on",
                                      "off", "sw", "switch", "status", "ok", "en"}):
        return "status"
    return "other"


def _reason(category: str, entry: TagEntry) -> str:
    reasons = {
        "analog_pv": "Analog process value (engineering units) -- primary SCADA metric.",
        "setpoint": "Operator setpoint / scale-range register.",
        "alarm": "Alarm / fault / interlock bit.",
        "status": "Field device status (auto/aux/disconnect/run).",
        "command": "Command / output to a device.",
        "field_io": "Physical field I/O point (aliased channel).",
        "comms": "Drive/network communications structure -- not an operator metric.",
        "internal": "Scaling-AOI / loop instance internal -- not directly meaningful.",
        "config": "Configurator / buffer / clock / diagnostic -- not a process metric.",
        "other": "Unclassified; review before including.",
    }
    return reasons.get(category, "")


def _is_field_device(name: str) -> bool:
    """True when a tag name follows a physical-field-device naming convention."""
    tokens = {t.lower() for t in _tokens(name)}
    if tokens & _FIELD_TOKENS:
        return True
    return _has(name, "aliasdin", "aliasain", "aliasdout", "aliasaout", "e_stop")


def is_export_relevant(entry: TagEntry, write_map: Optional[TagWriteMap] = None) -> bool:
    """Balanced relevance discriminator for the curated default (BUG-007).

    Only operator-facing (KEY) categories qualify. Analog PVs, setpoints and physical
    field I/O are always kept -- these carry positive process/scale/wire evidence and
    are frequently written by instructions the write engine does not model (e.g. SCP).
    Alarms, status and command bits are kept only with live evidence: written by logic,
    or a recognized physical-field device. This prunes dead scratch bits that merely
    happen to match a status/command token while preserving real device points.
    """
    cat = classify_category(entry)
    if cat not in KEY_CATEGORIES:
        return False
    if cat in ("analog_pv", "setpoint", "field_io", "alarm"):
        return True
    # status / command
    if write_map is None:
        return True  # no logic available -> keep (back-compat)
    if write_map.is_written(entry.name):
        return True
    return _is_field_device(entry.name)


def candidate_inventory(db: IgnitionTagDB,
                        write_map: Optional[TagWriteMap] = None) -> List[Dict[str, object]]:
    """Categorized inventory of every OPC-addressable tag, with include recommendation."""
    out: List[Dict[str, object]] = []
    for entry in db.opc_addressable_tags():
        category = classify_category(entry)
        out.append({
            "name": entry.name,
            "scope": entry.scope,
            "data_type": entry.data_type,
            "comment": entry.comment,
            "signal_type": classify_signal_type(tag_name=entry.name, description=entry.comment),
            "category": category,
            "recommended": is_export_relevant(entry, write_map),
            "reason": _reason(category, entry),
        })
    out.sort(key=lambda c: (not c["recommended"], str(c["category"]), str(c["name"])))
    return out


def key_process_metric_names(db: IgnitionTagDB,
                             write_map: Optional[TagWriteMap] = None) -> List[str]:
    """Base names of the curated default selection: the operator-facing (relevance-
    discriminated) tags plus expandable UDT/AOI struct roots (whose atomic members the
    generator expands downstream, BUG-008)."""
    return [entry.name for entry in db.opc_addressable_tags()
            if is_export_relevant(entry, write_map)
            or is_expandable_structure(entry.data_type)]


def list_ignition_tag_candidates(file_path: str) -> Dict[str, object]:
    """Present the full, categorized candidate inventory for agent-driven curation."""
    db = load_tag_db(file_path)

    # 1. Run the write-detection engine on the resolved L5X (handles ACD too), then
    #    categorize/recommend through the shared relevance discriminator so this
    #    inventory's 'recommended' set matches what generate_ignition_tags builds.
    write_map = build_write_map(db.l5x_path)
    candidates = candidate_inventory(db, write_map)

    # 2. Expand Composite Structures (FData1, TData1, Btu1, SCP, TOTALIZER, etc.)
    expanded_candidates = []
    for c in candidates:
        tag_name = str(c["name"])
        dt = str(c["data_type"])
        c["is_written"] = write_map.is_written(tag_name) if write_map else True

        expanded_candidates.append(c)

        if is_expandable_structure(dt):
            members = expand_structure_members(tag_name, dt, str(c["comment"]))
            for m in members:
                expanded_candidates.append({
                    "name": m["plc_tag"],
                    "scope": c["scope"],
                    "data_type": m["dataType"],
                    "comment": m["doc_desc"],
                    "signal_type": classify_signal_type(tag_name=m["plc_tag"], description=m["doc_desc"]),
                    "category": "analog_pv" if m["engUnit"] else "status",
                    "recommended": True,
                    "reason": f"Expanded SCADA metric member from {dt} structure",
                    "is_written": True
                })

    by_category: Dict[str, int] = {}
    for c in expanded_candidates:
        cat = str(c["category"])
        by_category[cat] = by_category.get(cat, 0) + 1
    recommended = [c["name"] for c in expanded_candidates if c.get("recommended", False)]

    # 3. Detect Ambiguities for interactive agent guidance queries
    queries = []
    try:
        tree = ET.parse(str(db.l5x_path))
        raw_queries = detect_tag_ambiguities(tree.getroot())
        queries = [q.to_dict() for q in raw_queries]
    except Exception:
        pass

    return {
        "success": True,
        "project_name": db.controller_name,
        "total_candidates": len(expanded_candidates),
        "recommended_count": len(recommended),
        "category_counts": dict(sorted(by_category.items())),
        "recommended_tags": recommended,
        "candidates": expanded_candidates,
        "guidance_queries": queries,
        "note": ("Review the categorized candidates, decide which tags matter for this "
                 "SCADA import (ask the user if unsure), then call generate_ignition_tags "
                 "with target_tags set to your curated selection. 'recommended' marks the "
                 "operator-facing default; override freely."),
    }

