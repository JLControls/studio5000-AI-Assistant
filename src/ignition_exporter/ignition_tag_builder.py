#!/usr/bin/env python3
"""Generalized Ignition v8.1+ tag-tree builder.

Ported from the project-specific ``build_ignition_tags.py`` reference, stripped of
all hardcoded tag names/hierarchy and with two corrections baked in:

* **Correction #1 -- value deadbands stay at Ignition defaults.** The builder
  never emits ``historicalDeadband``, ``historicalDeadbandMode``, ``deadband`` or
  ``deadbandStyle``. Only ``historyEnabled``, ``historyProvider``,
  ``historyMaxAge`` and ``historyTimeDeadband`` are written.
* **Correction #2 -- correct Ignition scaling model.** When Ignition must convert,
  ``scaleMode="Linear"`` plus ``rawLow/rawHigh -> scaledLow/scaledHigh`` carry the
  real value conversion; ``engLow/engHigh/engUnit`` are display/deadband metadata
  only. When the exposed tag is already engineering, only ``engLow/engHigh/engUnit``
  are set (no scaleMode/raw/scaled).

Generated output requires engineering review + Ignition validation before use.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Set, Tuple

from .aoi_structure_parser import is_expandable_structure
from .aoi_structure_parser import is_expandable_structure
from .l5x_tags import IgnitionTagDB

# The Ignition scaling property keys are centralized here so they are the single
# source of truth (confirmed against the Ignition 8.1 tag-scaling docs).
SCALE_MODE_KEY = "scaleMode"
RAW_LOW_KEY, RAW_HIGH_KEY = "rawLow", "rawHigh"
SCALED_LOW_KEY, SCALED_HIGH_KEY = "scaledLow", "scaledHigh"

BASELINE_FILE_NAME = "ignitionTags.json"

# Keys that must never appear in generated output (correction #1).
FORBIDDEN_DEADBAND_KEYS = frozenset({
    "historicalDeadband", "historicalDeadbandMode", "deadband", "deadbandStyle",
})


def sanitize_name(name: str) -> str:
    """Sanitize text for Ignition node-naming compliance.

    ``&`` -> ``and``, ``/`` -> space, strip ``deg () : " ' * ? < > |``, collapse
    whitespace. Prevents Ignition ``"Error loading node"`` import failures.
    """
    s = name.replace("&", "and").replace("/", " ")
    s = re.sub(r'[°\(\):"\'\*\?<>\|]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


class IgnitionTagBuilder:
    """Constructs sanitized, correctly-scaled, historized Ignition tag trees."""

    def __init__(self, device_name: str, opc_server: str = "Ignition OPC UA Server",
                 history_provider: str = "Ignition_SCADA",
                 tag_db: Optional[IgnitionTagDB] = None):
        self.device_name = device_name
        self.opc_prefix = f"ns=1;s=[{device_name}]"
        self.opc_server = opc_server
        self.history_provider = history_provider
        self.tag_db = tag_db
        self.inaccessible_tags: List[Tuple[str, str, str]] = []

    # -- tag construction --------------------------------------------------
    def tag(self, name: str, plc_tag: str, data_type: str, *, unit: str = "",
            eng_low: Optional[float] = None, eng_high: Optional[float] = None,
            requires_scaling: bool = False,
            raw_low: Optional[float] = None, raw_high: Optional[float] = None,
            scaled_low: Optional[float] = None, scaled_high: Optional[float] = None,
            doc: str = "", tooltip: str = "", history: bool = False,
            time_deadband: int = 15, max_age: int = 24,
            origin: str = "", controls: str = "", read_only: bool = True) -> Optional[Dict]:
        """Create an OPC ``AtomicTag`` dict.

        Returns ``None`` (and records it) when the tag is ``ExternalAccess="None"``
        and cannot be read over OPC UA. Program-scope tags get a
        ``Program:<ProgramName>.`` prefix on their ``opcItemPath``.
        """
        base_tag = plc_tag.split(".")[0]

        if self.tag_db is not None:
            entry = self.tag_db.get(base_tag)
            if entry is not None:
                if entry.external_access == "None":
                    self.inaccessible_tags.append((name, plc_tag, entry.scope))
                    return None
                if entry.program and not plc_tag.startswith("Program:"):
                    plc_tag = f"Program:{entry.program}.{plc_tag}"

        clean_name = sanitize_name(name)
        clean_unit = sanitize_name(unit) if unit else ""
        clean_doc = doc.strip() if doc else clean_name
        clean_tooltip = tooltip.strip() if tooltip else clean_doc

        enhanced_doc = f"{clean_doc}\n\nValue Set By: {origin}\nControls: {controls}" if (origin or controls) else clean_doc

        t: Dict[str, object] = {
            "dataType": data_type,
            "documentation": enhanced_doc,
            "name": clean_name,
            "opcItemPath": f"{self.opc_prefix}{plc_tag}",
            "opcServer": self.opc_server,
            "readOnly": bool(read_only),
            "tagType": "AtomicTag",
            "tooltip": sanitize_name(clean_tooltip),
            "valueSource": "opc",
        }

        # Engineering display range / deadband metadata (correction #2): always the
        # engineering values, independent of whether Ignition converts.
        if clean_unit:
            t["engUnit"] = clean_unit
        if eng_low is not None:
            t["engLow"] = float(eng_low)
        if eng_high is not None:
            t["engHigh"] = float(eng_high)

        # Real value conversion, ONLY when Ignition must scale raw hardware.
        if requires_scaling and None not in (raw_low, raw_high, scaled_low, scaled_high):
            t[SCALE_MODE_KEY] = "Linear"
            t[RAW_LOW_KEY] = float(raw_low)
            t[RAW_HIGH_KEY] = float(raw_high)
            t[SCALED_LOW_KEY] = float(scaled_low)
            t[SCALED_HIGH_KEY] = float(scaled_high)
            # If no distinct engineering display range was supplied, mirror the
            # scaled endpoints so meters/deadbands have a range to work with.
            t.setdefault("engLow", float(scaled_low))
            t.setdefault("engHigh", float(scaled_high))

        self._apply_history(t, history, time_deadband, max_age)
        return t

    def expression_tag(self, name: str, expression: str, data_type: str, *,
                       unit: str = "", eng_low: Optional[float] = None,
                       eng_high: Optional[float] = None, doc: str = "",
                       tooltip: str = "", history: bool = False,
                       time_deadband: int = 15, max_age: int = 24,
                       origin: str = "", controls: str = "",
                       read_only: bool = True) -> Dict:
        """Create an expression (``valueSource="expr"``) ``AtomicTag`` dict."""
        clean_name = sanitize_name(name)
        clean_unit = sanitize_name(unit) if unit else ""
        clean_doc = doc.strip() if doc else clean_name
        clean_tooltip = tooltip.strip() if tooltip else clean_doc
        enhanced_doc = f"{clean_doc}\n\nValue Set By: {origin}\nControls: {controls}" if (origin or controls) else clean_doc

        t: Dict[str, object] = {
            "dataType": data_type,
            "documentation": enhanced_doc,
            "expression": expression,
            "name": clean_name,
            "readOnly": bool(read_only),
            "tagType": "AtomicTag",
            "tooltip": sanitize_name(clean_tooltip),
            "valueSource": "expr",
        }
        if clean_unit:
            t["engUnit"] = clean_unit
        if eng_low is not None:
            t["engLow"] = float(eng_low)
        if eng_high is not None:
            t["engHigh"] = float(eng_high)
        self._apply_history(t, history, time_deadband, max_age)
        return t

    def _apply_history(self, t: Dict[str, object], history: bool,
                       time_deadband: int, max_age: int) -> None:
        """Write historian properties (correction #1: no value deadbands, ever)."""
        if not history:
            return
        t["historyEnabled"] = True
        t["historyProvider"] = self.history_provider
        t["historyMaxAge"] = int(max_age)
        t["historyTimeDeadband"] = int(time_deadband)

    def folder(self, name: str, tags: List[Optional[Dict]]) -> Dict:
        """Create a ``Folder`` node, dropping ``None`` children (filtered tags)."""
        return {
            "name": sanitize_name(name),
            "tagType": "Folder",
            "tags": [t for t in tags if t is not None],
        }

    def serialize(self, data: Dict) -> str:
        """Serialize to JSON with Ignition escaping (``\\u003d``/``\\u0026``) and sorted keys."""
        raw_json = json.dumps(data, indent=2, sort_keys=True)
        # Ignition serializes '=' and '&' in opcItemPath as unicode escapes. Build
        # the escape prefix from chr(92) (backslash) to keep it literal in output.
        esc = chr(92)  # backslash
        return raw_json.replace("=", esc + "u003d").replace("&", esc + "u0026")


def flatten_tags(data, parent_path: str = "") -> Tuple[Dict[str, Dict], Set[str]]:
    """Recursively flatten a tag tree into ``(tags_by_opc, folder_paths)``."""
    tags_dict: Dict[str, Dict] = {}
    folders_set: Set[str] = set()

    if isinstance(data, dict):
        tag_type = data.get("tagType")
        name = data.get("name", "")
        current_path = f"{parent_path}/{name}" if parent_path else name

        if tag_type == "Folder":
            folders_set.add(current_path)
            for child in data.get("tags", []):
                sub_tags, sub_folders = flatten_tags(child, current_path)
                tags_dict.update(sub_tags)
                folders_set.update(sub_folders)
        elif "tags" in data and isinstance(data["tags"], list):
            for child in data["tags"]:
                sub_tags, sub_folders = flatten_tags(child, parent_path)
                tags_dict.update(sub_tags)
                folders_set.update(sub_folders)
        else:
            opc = data.get("opcItemPath", name)
            tags_dict[opc] = {
                "full_path": current_path,
                "name": name,
                "opcItemPath": opc,
                "valueSource": data.get("valueSource", "opc"),
            }
    elif isinstance(data, list):
        for item in data:
            sub_tags, sub_folders = flatten_tags(item, parent_path)
            tags_dict.update(sub_tags)
            folders_set.update(sub_folders)

    return tags_dict, folders_set


_UDT_TYPES_REQUIRING_MEMBER = {"COUNTER", "TIMER"}


def verify_tree_against_l5x(tag_db: IgnitionTagDB, tree: Dict) -> Dict[str, object]:
    """Verify every OPC tag in ``tree`` exists in the L5X tag DB.

    Raises ``ValueError`` on synthetic (non-existent) tags, program-scope tags
    missing their ``Program:`` prefix, or bare COUNTER/TIMER/expandable-UDT-AOI
    struct roots without an atomic member. Returns a summary dict on success.
    """
    enh_tags, _ = flatten_tags(tree)
    missing: List[str] = []
    prefix_issues: List[str] = []
    udt_issues: List[str] = []

    for opc, info in enh_tags.items():
        if info.get("valueSource") == "expr":
            continue
        m = re.search(r'\[[^\]]+\](.*)$', opc)
        if not m:
            continue
        plc_ref = m.group(1)

        if plc_ref.startswith("Program:"):
            _, _, remainder = plc_ref.partition(".")
            base_tag = remainder.split(".")[0]
            sub_member = remainder.split(".")[1] if "." in remainder else None
        else:
            base_tag = plc_ref.split(".")[0]
            sub_member = plc_ref.split(".")[1] if "." in plc_ref else None

        entry = tag_db.get(base_tag)
        if entry is None:
            missing.append(f"{info['full_path']} -> {base_tag}")
            continue
        if entry.program and not plc_ref.startswith("Program:"):
            prefix_issues.append(f"{info['full_path']} -> {base_tag} (in {entry.program})")
        if not sub_member and (entry.data_type in _UDT_TYPES_REQUIRING_MEMBER
                               or is_expandable_structure(entry.data_type)):
            udt_issues.append(f"{info['full_path']} -> {base_tag} ({entry.data_type})")

    if missing:
        raise ValueError(
            "Synthetic/non-existent tags are prohibited; not found in L5X: " + "; ".join(missing))
    if prefix_issues:
        raise ValueError(
            "Program-scoped tags must carry a 'Program:<Name>.' opcItemPath prefix: "
            + "; ".join(prefix_issues))
    if udt_issues:
        raise ValueError(
            "COUNTER/TIMER and complex UDT/AOI struct tags must address an atomic "
            "member (e.g. .PRE/.ACC/.DN, .Flow/.Tot, .Temp); Ignition cannot read a "
            "struct root as a scalar OPC item: " + "; ".join(udt_issues))

    return {"verified_tag_count": len(enh_tags), "success": True}
