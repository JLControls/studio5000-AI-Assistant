#!/usr/bin/env python3
"""Case-sensitive OPC item-path audit against the L5X controller tag DB (tool #3).

Logix OPC UA servers require exact-case tag references, so a binding that differs
only in case (``..._LP_...`` vs ``..._Lp_...``) silently fails at runtime. This
audit flattens an Ignition JSON export, extracts each ``opcItemPath``'s PLC tag
reference, and compares it against the project tag DB, reporting three problem
classes: ``missing_tags``, ``case_mismatches``, and ``external_access_none``.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List

from .ignition_tag_builder import flatten_tags
from .l5x_tags import load_tag_db

_OPC_PLC_REF_RE = re.compile(r'\[[^\]]+\](.*)$')


def _plc_base_tag(opc_item_path: str) -> str:
    """Extract the base PLC tag name from an opcItemPath.

    Strips the ``ns=1;s=[Device]`` prefix and any ``Program:<name>.`` scope, then
    drops UDT member/array suffixes to leave the base tag Logix would resolve.
    """
    m = _OPC_PLC_REF_RE.search(opc_item_path)
    if not m:
        return ""
    plc_ref = m.group(1)
    if plc_ref.startswith("Program:"):
        _, _, plc_ref = plc_ref.partition(".")
    return plc_ref.split(".")[0].split("[")[0]


def audit_opc_item_paths(ignition_json_path: str, l5x_file_path: str) -> Dict[str, object]:
    """Audit every ``opcItemPath`` in an Ignition export against the L5X tag DB."""
    with open(ignition_json_path, "r", encoding="utf-8") as f:
        tree = json.load(f)

    db = load_tag_db(l5x_file_path)
    # Case-insensitive index: lower(name) -> exact name, for mismatch detection.
    ci_index: Dict[str, str] = {name.lower(): name for name in db.tags}

    flat, _ = flatten_tags(tree)

    missing_tags: List[Dict[str, str]] = []
    case_mismatches: List[Dict[str, str]] = []
    external_access_none: List[Dict[str, str]] = []
    checked = 0

    for opc, info in flat.items():
        if info.get("valueSource") == "expr":
            continue
        base = _plc_base_tag(opc)
        if not base:
            continue
        checked += 1

        if base in db.tags:
            if db.tags[base].external_access == "None":
                external_access_none.append({
                    "opc_path": opc,
                    "plc_tag": base,
                    "severity": "Error (ExternalAccess=None cannot be read over OPC UA)",
                })
            continue

        actual = ci_index.get(base.lower())
        if actual is not None:
            case_mismatches.append({
                "opc_path": opc,
                "referenced_plc_tag": base,
                "actual_plc_tag": actual,
                "severity": "Warning (Logix OPC servers require exact case)",
            })
        else:
            missing_tags.append({
                "opc_path": opc,
                "referenced_plc_tag": base,
                "severity": "Error (no such tag in L5X)",
            })

    if missing_tags:
        status = "FAILED"
    elif case_mismatches or external_access_none:
        status = "PASSED_WITH_WARNINGS"
    else:
        status = "PASSED"

    return {
        "success": True,
        "audit_status": status,
        "total_tags_checked": checked,
        "missing_tags": missing_tags,
        "case_mismatches": case_mismatches,
        "external_access_none": external_access_none,
    }
