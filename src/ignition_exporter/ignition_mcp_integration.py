#!/usr/bin/env python3
"""MCP integration engine for the Ignition exporter.

Exposes :class:`IgnitionMCPIntegration` -- one async method per MCP tool, mirroring
``TagMCPIntegration``. The engine is pure and offline (no vector DB, no
sentence-transformers), so the server's lazy property is trivial and ``--test``
stays fast.

Generated PLC/SCADA output always requires engineering review and Studio 5000 /
Ignition validation before use on a live control system.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from .analog_scaling import detect_analog_scaling, extract_analog_scaling
from .folder_structures import (
    build_folder_grouping,
    propose_folder_structures,
)
from .historian_rules import history_defaults_for, suggest_historian_config
from .ignition_tag_builder import (
    BASELINE_FILE_NAME,
    IgnitionTagBuilder,
    flatten_tags,
    sanitize_name,
    verify_tree_against_l5x,
)
from .l5x_tags import IgnitionTagDB, load_tag_db
from .opc_audit import audit_opc_item_paths
from .tag_curation import key_process_metric_names, list_ignition_tag_candidates

# Logix atomic data types -> Ignition data types.
_IGNITION_DTYPE = {
    "BOOL": "Boolean", "BIT": "Boolean",
    "SINT": "Int1", "INT": "Int2", "DINT": "Int4", "LINT": "Int8",
    "USINT": "Int1", "UINT": "Int2", "UDINT": "Int4",
    "REAL": "Float4", "LREAL": "Float8",
    "STRING": "String",
}
# UDT member expansion for the common predefined structures: member -> Ignition type.
_UDT_MEMBERS = {
    "COUNTER": {"ACC": "Int4", "PRE": "Int4", "DN": "Boolean"},
    "TIMER": {"ACC": "Int4", "PRE": "Int4", "DN": "Boolean"},
}
# Data types that are scaling blocks / non-atomic and are not exported directly.
_STRUCTLIKE_SKIP = set(_UDT_MEMBERS)

# Folders with fewer than this many tags are merged into a single "System" folder to
# avoid a tree fragmented into dozens of one-off folders.
_MIN_FOLDER_SIZE = 2


def _ignition_dtype(logix_type: str) -> Optional[str]:
    return _IGNITION_DTYPE.get(logix_type.upper())


def _origin_for(plc_tag: str, comment: str, data_type: str) -> str:
    """Generalized 'Value Set By' origin from signal-type keywords (no hardcoding)."""
    text = f"{plc_tag} {comment}".lower()
    if data_type in ("Boolean",):
        if "auto" in text:
            return f"Auto/Hand selector or mode-enable contact ({plc_tag})."
        if "aux" in text:
            return f"Motor-starter auxiliary run-feedback contact ({plc_tag})."
        if any(k in text for k in ("alarm", "alm", "fault", "flt", "fail")):
            return f"PLC alarm / interlock logic bit ({plc_tag})."
        if any(k in text for k in ("estop", "e-stop")):
            return f"Hardwired safety / E-Stop contact ({plc_tag})."
        return f"Digital field input / status bit ({plc_tag})."
    if any(k in text for k in ("set", "setpoint", "_sc")):
        return f"Operator HMI setpoint / configuration register ({plc_tag})."
    if any(k in text for k in ("btu", "rep", "totalizer")):
        return f"Calculated in a PLC math / reporting routine ({plc_tag})."
    return f"PLC process variable / analog register ({plc_tag})."


def _controls_for(comment: str, plc_tag: str) -> str:
    """Generalized 'Controls' description from signal-type keywords."""
    text = f"{comment} {plc_tag}".lower()
    if "pressure" in text:
        return "Modulates pump speed and triggers pressure high/low alarms."
    if "temp" in text:
        return "Modulates heating/cooling and triggers temperature safety cutouts."
    if any(k in text for k in ("level", "height", "volume")):
        return "Controls fill valves, low-suction cutouts, and high/low level alarms."
    if any(k in text for k in ("speed", "hz", "vfd")):
        return "Controls VFD output frequency and motor operating speed."
    if any(k in text for k in ("alarm", "alm", "fault", "fail", "estop")):
        return "Triggers SCADA alarm banner, horn output, and safety shutdowns."
    return "Monitored by the SCADA HMI for process control and status display."


class _ExportItem:
    """One tag to export: a resolved PLC ref plus its Ignition metadata."""

    __slots__ = ("plc_ref", "base", "data_type", "comment", "scaling")

    def __init__(self, plc_ref: str, base: str, data_type: str, comment: str,
                 scaling: Optional[Dict] = None):
        self.plc_ref = plc_ref
        self.base = base
        self.data_type = data_type
        self.comment = comment
        self.scaling = scaling


def _scaling_by_ref(points: List[Dict]) -> Dict[str, Dict]:
    """Index scaling points by their recommended OPC tag's PLC ref."""
    out: Dict[str, Dict] = {}
    for p in points:
        ref = p.get("recommended_opc_tag")
        if ref:
            out[ref] = p
    return out


def _collect_export_items(db: IgnitionTagDB, scaling_points: List[Dict],
                          selected: Optional[set] = None) -> Tuple[List[_ExportItem], List[str]]:
    """Decide which PLC refs become Ignition tags.

    Analog points contribute their recommended engineering tag (with scaling info);
    COUNTER/TIMER tags expand to atomic members; other atomic tags export directly.
    ``ExternalAccess="None"`` tags are excluded and reported. When ``selected`` is
    given, only tags whose base name is in that set are exported (curation).
    """
    def _wanted(base: str) -> bool:
        return selected is None or base in selected

    scaling_map = _scaling_by_ref(scaling_points)
    seen: set = set()
    items: List[_ExportItem] = []
    excluded: List[str] = []

    # 1. Analog scaling recommended tags first (they carry scaling metadata).
    for ref, point in scaling_map.items():
        base = ref.split(".")[0]
        if not _wanted(base):
            continue
        entry = db.get(base)
        if entry is not None and entry.external_access == "None":
            excluded.append(ref)
            continue
        items.append(_ExportItem(ref, base, "REAL", entry.comment if entry else "", point))
        seen.add(ref)
        seen.add(base)

    # 2. Remaining addressable tags.
    for entry in db.tags.values():
        if entry.name in seen or not _wanted(entry.name):
            continue
        if entry.external_access == "None":
            excluded.append(entry.name)
            continue
        dtype = entry.data_type.upper()
        if dtype in _UDT_MEMBERS:
            for member, _ign in _UDT_MEMBERS[dtype].items():
                ref = f"{entry.name}.{member}"
                items.append(_ExportItem(ref, entry.name, dtype, entry.comment))
            continue
        if _ignition_dtype(dtype) is None:
            # Unknown struct / scaling-block instance -> not atomically addressable.
            continue
        items.append(_ExportItem(entry.name, entry.name, entry.data_type, entry.comment))

    return items, excluded


def _member_dtype(item: _ExportItem) -> str:
    """Ignition data type for an export item, resolving UDT members and scaling."""
    if "." in item.plc_ref:
        member = item.plc_ref.split(".")[-1]
        udt = _UDT_MEMBERS.get(item.data_type.upper())
        if udt and member in udt:
            return udt[member]
        return "Float4"  # scaling-block .Output and similar analog members
    return _ignition_dtype(item.data_type) or "Float4"


def _build_tag(builder: IgnitionTagBuilder, item: _ExportItem,
               enable_history: bool) -> Optional[Dict]:
    """Construct a single Ignition tag dict for an export item."""
    ign_dtype = _member_dtype(item)
    name = sanitize_name(item.plc_ref.replace(".", " "))
    doc = item.comment or name

    unit = ""
    eng_low = eng_high = raw_low = raw_high = scaled_low = scaled_high = None
    requires_scaling = False
    if item.scaling:
        unit = item.scaling.get("eng_unit", "") or ""
        eng_low = item.scaling.get("eng_low")
        eng_high = item.scaling.get("eng_high")
        requires_scaling = bool(item.scaling.get("requires_ignition_scaling"))
        if requires_scaling:
            raw_low = item.scaling.get("raw_low")
            raw_high = item.scaling.get("raw_high")
            scaled_low = item.scaling.get("scaled_low")
            scaled_high = item.scaling.get("scaled_high")

    history = False
    time_deadband = 15
    if enable_history:
        defaults = history_defaults_for(item.plc_ref, item.comment)
        history = defaults["history"]
        time_deadband = defaults["time_deadband"]

    return builder.tag(
        name, item.plc_ref, ign_dtype,
        unit=unit, eng_low=eng_low, eng_high=eng_high,
        requires_scaling=requires_scaling,
        raw_low=raw_low, raw_high=raw_high,
        scaled_low=scaled_low, scaled_high=scaled_high,
        doc=doc,
        origin=_origin_for(item.plc_ref, item.comment, ign_dtype),
        controls=_controls_for(item.comment, item.plc_ref),
        history=history, time_deadband=time_deadband,
    )


def _grouped_tree(builder: IgnitionTagBuilder, db: IgnitionTagDB,
                  items: List[_ExportItem], tags_by_ref: Dict[str, Dict],
                  model: str, root_name: str) -> Dict:
    """Nest built tag dicts into a folder tree per the grouping model."""
    base_entries = {}
    for item in items:
        entry = db.get(item.base)
        if entry is not None:
            base_entries[entry.name] = entry
    grouping = build_folder_grouping(list(base_entries.values()), model)
    label_of = {name: label for label, names in grouping.items() for name in names}

    folders: Dict[str, List[Dict]] = {}
    for item in items:
        tag = tags_by_ref.get(item.plc_ref)
        if tag is None:
            continue
        label = label_of.get(item.base, "System")
        folders.setdefault(label, []).append(tag)

    # Collapse fragmentation: single-tag folders (junk name-stems) are gathered into
    # one "System" folder so the tree reads as meaningful process areas, not dozens
    # of one-off folders.
    system_bucket: List[Dict] = []
    kept: Dict[str, List[Dict]] = {}
    for label, tags in folders.items():
        if len(tags) < _MIN_FOLDER_SIZE:
            system_bucket.extend(tags)
        else:
            kept[label] = tags
    if system_bucket:
        kept.setdefault("System", []).extend(system_bucket)

    folder_nodes = [builder.folder(label, tags) for label, tags in sorted(kept.items())]
    return builder.folder(root_name, folder_nodes)


class IgnitionMCPIntegration:
    """Offline engine backing the six Ignition SCADA MCP tools."""

    def __init__(self):
        self.initialized = True

    # -- tool #1 -----------------------------------------------------------
    async def extract_analog_scaling(self, l5x_file_path: str,
                                     target_tags: Optional[List[str]] = None) -> Dict:
        """Detect analog scaling per point (signal-flow aware)."""
        return extract_analog_scaling(l5x_file_path, target_tags=target_tags)

    # -- discovery: present candidates for agent-driven curation -----------
    async def list_ignition_tag_candidates(self, l5x_file_path: str) -> Dict:
        """Present the full, categorized tag inventory so the agent can curate."""
        return list_ignition_tag_candidates(l5x_file_path)

    # -- tool #2 -----------------------------------------------------------
    async def generate_ignition_tags(self, l5x_file_path: str, device_name: str,
                                     output_file_path: str,
                                     folder_hierarchy_model: str = "PhysicalSubsystem",
                                     enable_history_defaults: bool = True,
                                     target_tags: Optional[List[str]] = None,
                                     selection: str = "key_process_metrics") -> Dict:
        """Build and write an Ignition v8.1+ JSON tag export from an L5X/ACD project.

        Selection precedence: an explicit ``target_tags`` list (the agent's curated
        choice) wins; otherwise ``selection`` chooses between ``"key_process_metrics"``
        (curated default -- operator-facing PVs/setpoints/alarms/status/commands/field
        I/O) and ``"all"`` (every OPC-addressable tag). Use
        ``list_ignition_tag_candidates`` first to curate deliberately.
        """
        if os.path.basename(output_file_path) == BASELINE_FILE_NAME:
            return {
                "success": False,
                "error": (f"Refusing to write '{BASELINE_FILE_NAME}': it is the "
                          "read-only baseline. Choose a different output file name."),
            }

        db = load_tag_db(l5x_file_path)
        builder = IgnitionTagBuilder(device_name, tag_db=db)
        scaling_points = detect_analog_scaling(db)

        if target_tags:
            selected: Optional[set] = {t.split(".")[0] for t in target_tags}
            selection_mode = "target_tags"
        elif selection == "all":
            selected = None
            selection_mode = "all"
        else:
            selected = set(key_process_metric_names(db))
            selection_mode = "key_process_metrics"

        items, excluded = _collect_export_items(db, scaling_points, selected)

        tags_by_ref: Dict[str, Dict] = {}
        for item in items:
            tag = _build_tag(builder, item, enable_history_defaults)
            if tag is not None:
                tags_by_ref[item.plc_ref] = tag

        root_name = sanitize_name(device_name) or db.controller_name
        tree = _grouped_tree(builder, db, items, tags_by_ref, folder_hierarchy_model, root_name)

        # Enforce zero synthetic tags before writing (raises on violation).
        verify_tree_against_l5x(db, tree)

        payload = builder.serialize(tree)
        with open(output_file_path, "w", encoding="utf-8") as f:
            f.write(payload)

        flat, folders = flatten_tags(tree)
        return {
            "success": True,
            "output_file": os.path.abspath(output_file_path),
            "device_name": device_name,
            "selection_mode": selection_mode,
            "folder_hierarchy_model": folder_hierarchy_model,
            "tags_written": len(flat),
            "folders_created": len(folders),
            "excluded_external_access_none": sorted(set(excluded)),
            "excluded_count": len(set(excluded)),
            "inaccessible_reported": builder.inaccessible_tags,
            "note": ("Generated SCADA tags require engineering review and Ignition "
                     "validation before deployment."),
        }

    # -- tool #3 -----------------------------------------------------------
    async def audit_opc_item_paths(self, ignition_json_path: str,
                                   l5x_file_path: str) -> Dict:
        """Case-sensitive audit of OPC item paths vs the L5X tag DB."""
        return audit_opc_item_paths(ignition_json_path, l5x_file_path)

    # -- tool #4 -----------------------------------------------------------
    async def suggest_historian_config(self, signal_type: Optional[str] = None,
                                       tag_name: Optional[str] = None,
                                       description: Optional[str] = None,
                                       eng_low: Optional[float] = None,
                                       eng_high: Optional[float] = None) -> Dict:
        """Recommend historian settings (value deadband is advisory only)."""
        return suggest_historian_config(
            signal_type=signal_type, tag_name=tag_name, description=description,
            eng_low=eng_low, eng_high=eng_high,
        )

    # -- tool #5 -----------------------------------------------------------
    async def propose_folder_structures(self, l5x_file_path: str,
                                        max_options: int = 3) -> Dict:
        """Propose candidate Ignition folder trees for a project."""
        return propose_folder_structures(l5x_file_path, max_options=max_options)

    # -- tool #6 -----------------------------------------------------------
    async def sanitize_ignition_nodes(self, names) -> Dict:
        """Preview Ignition name sanitization for a string or list of names."""
        if isinstance(names, str):
            names_list = [names]
        else:
            names_list = list(names or [])
        results = []
        for original in names_list:
            cleaned = sanitize_name(str(original))
            results.append({
                "original": original,
                "sanitized": cleaned,
                "changed": cleaned != original,
            })
        return {"success": True, "count": len(results), "results": results}
