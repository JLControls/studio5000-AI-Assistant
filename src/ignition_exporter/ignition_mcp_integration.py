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

from .analog_scaling import _guess_unit, detect_analog_scaling, extract_analog_scaling
from .aoi_structure_parser import (
    expand_structure_members,
    find_member_rule,
    is_expandable_structure,
)

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
from .tag_curation import build_write_map, key_process_metric_names, list_ignition_tag_candidates

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

    __slots__ = ("plc_ref", "base", "data_type", "comment", "scaling",
                 "ign_dtype", "eng_unit")

    def __init__(self, plc_ref: str, base: str, data_type: str, comment: str,
                 scaling: Optional[Dict] = None, ign_dtype: Optional[str] = None,
                 eng_unit: str = ""):
        self.plc_ref = plc_ref
        self.base = base
        self.data_type = data_type
        self.comment = comment
        self.scaling = scaling
        # Pre-resolved Ignition data type / engineering unit for expanded UDT-AOI
        # struct members (from aoi_structure_parser). None/"" for ordinary tags,
        # whose type/unit are derived downstream.
        self.ign_dtype = ign_dtype
        self.eng_unit = eng_unit


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
            for member, ign in _UDT_MEMBERS[dtype].items():
                ref = f"{entry.name}.{member}"
                items.append(_ExportItem(ref, entry.name, dtype, entry.comment,
                                         ign_dtype=ign))
            continue
        if is_expandable_structure(entry.data_type):
            # Complex UDT/AOI struct -> Ignition cannot read the struct root as a
            # scalar OPC item (BUG-008). Prune the root; export its atomic members.
            for m in expand_structure_members(entry.name, entry.data_type, entry.comment):
                items.append(_ExportItem(m["plc_tag"], entry.name, entry.data_type,
                                         m["doc_desc"] or entry.comment,
                                         ign_dtype=m["dataType"], eng_unit=m["engUnit"]))
            continue
        if _ignition_dtype(dtype) is None:
            # Unknown struct / scaling-block instance -> not atomically addressable.
            continue
        items.append(_ExportItem(entry.name, entry.name, entry.data_type, entry.comment))

    return items, excluded


def _expand_struct_overrides(db: IgnitionTagDB, overrides: List[Dict]) -> List[Dict]:
    """Expand any override whose ``plc_tag`` is a bare expandable struct root.

    Ignition cannot read a complex UDT/AOI struct root as a scalar OPC item
    (BUG-008), so an agent-supplied bare root (e.g. ``Com_CW`` of type ``FData1``) is
    replaced by one override per atomic member, inheriting the override's friendly
    ``name`` (as a title prefix), ``folder``, ``tooltip`` and ``documentation``. The
    member's Ignition data type / engineering unit ride along on private ``_ign_dtype``
    / ``_eng_unit`` keys. Member refs supplied directly (``Com_CW.Flow``) pass through.
    """
    expanded: List[Dict] = []
    for o in overrides:
        ref = (o.get("plc_tag") or "").strip()
        base = ref.split(".")[0]
        entry = db.get(base) if ref else None
        if (ref and "." not in ref and entry is not None
                and is_expandable_structure(entry.data_type)):
            base_name = o.get("name") or ""
            for m in expand_structure_members(entry.name, entry.data_type, base_name):
                expanded.append({
                    "plc_tag": m["plc_tag"],
                    "name": m["name"],
                    "documentation": o.get("documentation") or m["doc_desc"],
                    "tooltip": o.get("tooltip", ""),
                    "folder": o.get("folder", ""),
                    "_ign_dtype": m["dataType"],
                    "_eng_unit": m["engUnit"],
                })
        else:
            expanded.append(o)
    return expanded


def _collect_override_items(db: IgnitionTagDB, scaling_map: Dict[str, Dict],
                            overrides: List[Dict]) -> Tuple[List[_ExportItem], List[str]]:
    """Build export items directly from an agent-authored override list.

    The overrides ARE the curated set: one export item per ``plc_tag`` entry, in the
    given order, with its data type / comment resolved from the L5X and any detected
    scaling attached. ``ExternalAccess="None"`` tags are excluded and reported. A
    ``plc_tag`` absent from the L5X is still emitted so ``verify_tree_against_l5x``
    rejects it (no silent drop of a typo'd ref). Duplicate refs are de-duplicated.
    Struct-member refs resolve their per-member Ignition type/unit (BUG-008) either
    from expansion metadata (``_ign_dtype``) or the struct's member rule table.
    """
    items: List[_ExportItem] = []
    excluded: List[str] = []
    seen: set = set()
    for o in overrides:
        ref = (o.get("plc_tag") or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        base = ref.split(".")[0]
        entry = db.get(base)
        if entry is None:
            # Unknown ref: keep it so verification raises with a clear message.
            items.append(_ExportItem(ref, base, "REAL", "", scaling_map.get(ref)))
            continue
        if entry.external_access == "None":
            excluded.append(ref)
            continue
        ign_dtype = o.get("_ign_dtype")
        eng_unit = o.get("_eng_unit", "") or ""
        if ign_dtype is None and "." in ref:
            # Member ref supplied directly -> recover its type/unit from the rules.
            rule = find_member_rule(entry.data_type, ref[len(base):])
            if rule is not None:
                ign_dtype = rule.data_type
                eng_unit = eng_unit or rule.eng_unit
        items.append(_ExportItem(ref, base, entry.data_type, entry.comment,
                                 scaling_map.get(ref), ign_dtype=ign_dtype,
                                 eng_unit=eng_unit))
    return items, excluded


def _override_tree(builder: IgnitionTagBuilder, items: List[_ExportItem],
                   tags_by_ref: Dict[str, Dict], overrides_by_ref: Dict[str, Dict],
                   root_name: str) -> Dict:
    """Nest built tags into an arbitrary-depth folder tree from override ``folder`` paths.

    Each override's ``folder`` is a ``/``-delimited process hierarchy (e.g.
    ``"Boiler/Cold Water System/Pumps/CW Pump 1"``). A folder node's ``tags`` list
    mixes child AtomicTags and child Folder dicts, exactly how a nested Ignition tree
    is shaped. Tags with no ``folder`` sit at the root.
    """
    def _new_node() -> Dict:
        return {"tags": [], "sub": {}}

    root = _new_node()
    for item in items:
        tag = tags_by_ref.get(item.plc_ref)
        if tag is None:
            continue
        o = overrides_by_ref.get(item.plc_ref, {})
        parts = [sanitize_name(p) for p in (o.get("folder") or "").split("/") if p.strip()]
        node = root
        for part in parts:
            node = node["sub"].setdefault(part, _new_node())
        node["tags"].append(tag)

    def _to_folder(name: str, node: Dict) -> Dict:
        child_folders = [_to_folder(n, sub) for n, sub in sorted(node["sub"].items())]
        return builder.folder(name, node["tags"] + child_folders)

    top_folders = [_to_folder(n, sub) for n, sub in sorted(root["sub"].items())]
    return builder.folder(root_name, root["tags"] + top_folders)


def _member_dtype(item: _ExportItem) -> str:
    """Ignition data type for an export item, resolving UDT members and scaling."""
    if item.ign_dtype:
        # Pre-resolved by struct expansion (correct per-member type, incl. Boolean/Int).
        return item.ign_dtype
    if "." in item.plc_ref:
        member = item.plc_ref.split(".")[-1]
        udt = _UDT_MEMBERS.get(item.data_type.upper())
        if udt and member in udt:
            return udt[member]
        return "Float4"  # scaling-block .Output and similar analog members
    return _ignition_dtype(item.data_type) or "Float4"


def _build_tag(builder: IgnitionTagBuilder, item: _ExportItem,
               enable_history: bool, override: Optional[Dict] = None) -> Optional[Dict]:
    """Construct a single Ignition tag dict for an export item.

    When ``override`` (an agent-authored ``{name, documentation, tooltip}`` dict) is
    supplied, its friendly name/description/tooltip replace the mechanical raw-ref
    name and the generic "Value Set By / Controls" template is suppressed -- the agent
    is the author of record for that tag. Scaling and history behaviour are unchanged.
    """
    ign_dtype = _member_dtype(item)
    default_name = sanitize_name(item.plc_ref.replace(".", " "))
    if override is not None:
        name = override.get("name") or default_name
        doc = override.get("documentation") or item.comment or default_name
        tooltip = override.get("tooltip", "") or ""
        origin = controls = ""
    else:
        name = default_name
        doc = item.comment or default_name
        tooltip = ""
        origin = _origin_for(item.plc_ref, item.comment, ign_dtype)
        controls = _controls_for(item.comment, item.plc_ref)

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

    if not unit and item.eng_unit:
        # Known engineering unit from struct-member expansion (GPM, GAL, degF, ...).
        unit = item.eng_unit
    if not unit and ign_dtype in ("Float4", "Float8", "Int2", "Int4"):
        unit = _guess_unit(item.plc_ref, doc)


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
        doc=doc, tooltip=tooltip, origin=origin, controls=controls,
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
                                     selection: str = "key_process_metrics",
                                     tag_overrides: Optional[List[Dict]] = None) -> Dict:
        """Build and write an Ignition v8.1+ JSON tag export from an L5X/ACD project.

        Selection precedence: a non-empty ``tag_overrides`` list wins entirely -- it is
        the agent-authored curated set, each entry
        ``{plc_tag, name?, documentation?, tooltip?, folder?}`` supplying a friendly
        node name, description and ``/``-delimited process-folder path (this is how you
        restore human-readable output; the raw PLC ref, comment fallback and generic
        "Value Set By / Controls" template are used only for tags without an override).
        Otherwise an explicit ``target_tags`` list wins; otherwise ``selection`` chooses
        between ``"key_process_metrics"`` (curated default -- operator-facing
        PVs/setpoints/alarms/status/commands/field I/O) and ``"all"`` (every
        OPC-addressable tag). Use ``list_ignition_tag_candidates`` first to curate.
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
        scaling_map = _scaling_by_ref(scaling_points)

        overrides_by_ref: Dict[str, Dict] = {}
        if tag_overrides:
            # Expand bare struct-root overrides into their atomic members first, so the
            # friendly-name map and export items agree on the member refs (BUG-008).
            tag_overrides = _expand_struct_overrides(db, tag_overrides)
            overrides_by_ref = {
                (o.get("plc_tag") or "").strip(): o
                for o in tag_overrides if (o.get("plc_tag") or "").strip()
            }
            items, excluded = _collect_override_items(db, scaling_map, tag_overrides)
            selection_mode = "tag_overrides"
        else:
            if target_tags:
                selected: Optional[set] = {t.split(".")[0] for t in target_tags}
                selection_mode = "target_tags"
            elif selection == "all":
                selected = None
                selection_mode = "all"
            else:
                # Curated default: the Balanced relevance discriminator (BUG-007), shared
                # with list_ignition_tag_candidates via the write-detection map.
                write_map = build_write_map(l5x_file_path)
                selected = set(key_process_metric_names(db, write_map))
                selection_mode = "key_process_metrics"
            items, excluded = _collect_export_items(db, scaling_points, selected)

        tags_by_ref: Dict[str, Dict] = {}
        for item in items:
            tag = _build_tag(builder, item, enable_history_defaults,
                             override=overrides_by_ref.get(item.plc_ref))
            if tag is not None:
                tags_by_ref[item.plc_ref] = tag

        root_name = sanitize_name(device_name) or db.controller_name
        if tag_overrides:
            tree = _override_tree(builder, items, tags_by_ref, overrides_by_ref, root_name)
        else:
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
            "overrides_applied": len(overrides_by_ref),
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
