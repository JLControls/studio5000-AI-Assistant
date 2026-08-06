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
from typing import Dict, List

from tag_analyzer.tag_chunk import detect_function_from_description

from .analog_scaling import _has_scaling_signature, _normalize_members
from .historian_rules import classify_signal_type
from .l5x_tags import IgnitionTagDB, TagEntry, load_tag_db

# Operator-facing categories included in the curated "key process metrics" default.
KEY_CATEGORIES = frozenset({
    "analog_pv", "setpoint", "alarm", "status", "command", "field_io",
})
# Categories excluded from the curated default (still listed for the agent).
NOISE_CATEGORIES = frozenset({"comms", "config", "internal", "other"})


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
                 "test", "diag", "debug", "sim", "temp1", "tmp"}:
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


def candidate_inventory(db: IgnitionTagDB) -> List[Dict[str, object]]:
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
            "recommended": category in KEY_CATEGORIES,
            "reason": _reason(category, entry),
        })
    out.sort(key=lambda c: (not c["recommended"], str(c["category"]), str(c["name"])))
    return out


def key_process_metric_names(db: IgnitionTagDB) -> List[str]:
    """Names of the operator-facing tags that make up the curated default selection."""
    return [entry.name for entry in db.opc_addressable_tags()
            if classify_category(entry) in KEY_CATEGORIES]


def list_ignition_tag_candidates(file_path: str) -> Dict[str, object]:
    """Present the full, categorized candidate inventory for agent-driven curation."""
    db = load_tag_db(file_path)
    candidates = candidate_inventory(db)

    by_category: Dict[str, int] = {}
    for c in candidates:
        by_category[c["category"]] = by_category.get(str(c["category"]), 0) + 1
    recommended = [c["name"] for c in candidates if c["recommended"]]

    return {
        "success": True,
        "project_name": db.controller_name,
        "total_candidates": len(candidates),
        "recommended_count": len(recommended),
        "category_counts": dict(sorted(by_category.items())),
        "recommended_tags": recommended,
        "candidates": candidates,
        "note": ("Review the categorized candidates, decide which tags matter for this "
                 "SCADA import (ask the user if unsure), then call generate_ignition_tags "
                 "with target_tags set to your curated selection. 'recommended' marks the "
                 "operator-facing default; override freely."),
    }
