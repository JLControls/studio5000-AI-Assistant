#!/usr/bin/env python3
"""Signal-flow-aware analog scaling detection.

This is the net-new "smart decision" of the Ignition exporter. For every analog
scaling block in a project it decides which member holds the *engineering* value
the operator wants in SCADA, and whether Ignition still has to convert anything.

The core rule (see the plan / Ignition docs):

* A scaling block maps ``.Input in [InputMin, InputMax] -> .Output in [ScaledMin,
  ScaledMax]``.
* **Analog input** (4-20 mA / counts -> process value): expose the block's
  ``.Output`` (the scaled result). Engineering range = ``[ScaledMin, ScaledMax]``.
* **Analog output** (Hz command -> counts on the wire): expose the tag feeding the
  block's ``.Input`` (the command). Engineering range = ``[InputMin, InputMax]``.
* In both normal cases the exposed tag is already engineering, so Ignition does
  **not** re-scale -- only ``engLow/engHigh/engUnit`` are set downstream.
* **Raw-hardware fallback:** only when the sole OPC-addressable tag for a point is
  genuinely raw hardware (the engineering side is not addressable) does Ignition
  convert ``rawLow/rawHigh -> scaledLow/scaledHigh``.

Ranges are read from the authoritative decorated members; all-zero members (a
partial export) fall back to wired ``SCP`` constants. Standard raw ranges are
never assumed. Points that resolve to nothing are still returned, flagged
``scaling_source="none_found"`` with a ``warning`` -- never silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .l5x_tags import IgnitionTagDB, RungRef, load_tag_db

# Member names that identify a scaling block, case-insensitive. A tag/instruction
# is a scaling block when it carries the input+scaled range signature. Common
# spellings are aliased so project-defined AOI variants (SCP, SCPLim1, ...) match.
_MEMBER_ALIASES = {
    "inputmin": "input_min", "inmin": "input_min", "inrawmin": "input_min",
    "inputmax": "input_max", "inmax": "input_max", "inrawmax": "input_max",
    "scaledmin": "scaled_min", "scmin": "scaled_min", "ineumin": "scaled_min", "outmin": "scaled_min",
    "scaledmax": "scaled_max", "scmax": "scaled_max", "ineumax": "scaled_max", "outmax": "scaled_max",
    "input": "input", "in": "input",
    "output": "output", "out": "output",
}
_REQUIRED_RANGE_KEYS = ("input_min", "input_max", "scaled_min", "scaled_max")

# Rung instructions that perform scaling and expose ranges as ordered operands:
# NAME(Input, InputMin, InputMax, ScaledMin, ScaledMax, Output).
_SCP_INSTRUCTIONS = {"SCP", "SCPLIM1", "SCPLIM", "SCL"}

# Magnitude at/above which a range endpoint reads as raw counts rather than an
# engineering value -- used only as a direction tiebreaker.
_COUNT_LIKE_THRESHOLD = 1000.0

_UNIT_KEYWORDS = [
    ("hz", "Hz"), ("rpm", "RPM"), ("psi", "PSI"), ("bar", "bar"),
    ("gpm", "GPM"), ("lpm", "LPM"), ("degf", "degF"), ("temp", "degF"),
    ("gal", "gal"), ("btu", "BTU"), ("level", "in"), ("height", "in"),
    ("pres", "PSI"), ("psi", "PSI"), ("percent", "%"),
]
# Analog role markers, matched case-sensitively against the original tag names to
# leverage Rockwell CamelCase. Handles AIn/AOut, AnlgIn/AnlgOut, and the common
# AI/AO forms with a trailing channel digit (AI1, AO2) or scope underscore.
_INPUT_ROLE_RE = re.compile(r"A(?:nlg)?In|(?<![A-Za-z])AI\d*(?![A-Za-z])|Xmtr|Xducer|Transducer")
_OUTPUT_ROLE_RE = re.compile(r"A(?:nlg)?Out|(?<![A-Za-z])AO\d*(?![A-Za-z])|Cmd|Command")

# Common Rockwell name segments (conventions, NOT project-specific names) used to
# reduce a family of related tags to a shared stem. Leading scope/role markers and
# trailing scale-range markers are stripped so a raw alias-AI tag, its engineering
# PV, and its scale-range setpoint collapse to the same stem, e.g.
#   Com_AliasAIn_CW_Hdr_Pres  /  Com_CW_Hdr_Pres  /  Com_Set_CW_Hdr_Pres_Sc  ->  CW_Hdr_Pres
_STEM_LEADING_STRIP = frozenset({
    "com", "cmd", "set", "d", "raw", "alias", "aliasain", "aliasaout",
    "aliasdin", "aliasdout", "ain", "aout", "din", "dout",
})
_SCALE_SUFFIX_SEGMENTS = frozenset({"sc", "scale", "range", "rng"})
_RAW_AI_TYPES = frozenset({"INT", "DINT", "SINT", "UINT", "UDINT", "USINT"})
_ENG_PV_TYPES = frozenset({"REAL", "LREAL"})


@dataclass
class ScalingBlock:
    """A resolved scaling relationship for one analog point."""

    name: str
    input_min: Optional[float] = None
    input_max: Optional[float] = None
    scaled_min: Optional[float] = None
    scaled_max: Optional[float] = None
    input_tag: str = ""   # tag feeding .Input (raw side)
    output_tag: str = ""  # tag carrying .Output (engineering side)
    from_members: bool = False
    source: str = ""      # human-readable provenance
    comment: str = ""


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_members(members: Dict[str, str]) -> Dict[str, float]:
    """Map decorated member names to canonical range keys with float values."""
    out: Dict[str, float] = {}
    for raw_name, raw_val in members.items():
        canon = _MEMBER_ALIASES.get(raw_name.lower())
        if canon is None:
            continue
        val = _to_float(raw_val)
        if val is not None:
            out[canon] = val
    return out


def _has_scaling_signature(members: Dict[str, float]) -> bool:
    return all(key in members for key in _REQUIRED_RANGE_KEYS)


def _all_zero(block: ScalingBlock) -> bool:
    vals = [block.input_min, block.input_max, block.scaled_min, block.scaled_max]
    return all(v == 0 for v in vals)


def _count_like(value: Optional[float]) -> bool:
    return value is not None and abs(value) >= _COUNT_LIKE_THRESHOLD


def _find_member_blocks(db: IgnitionTagDB) -> Dict[str, ScalingBlock]:
    """Scaling blocks declared as decorated AOI/UDT instances (member values)."""
    blocks: Dict[str, ScalingBlock] = {}
    for tag in db.tags.values():
        if not tag.members:
            continue
        canon = _normalize_members(tag.members)
        if not _has_scaling_signature(canon):
            continue
        blocks[tag.name] = ScalingBlock(
            name=tag.name,
            input_min=canon.get("input_min"),
            input_max=canon.get("input_max"),
            scaled_min=canon.get("scaled_min"),
            scaled_max=canon.get("scaled_max"),
            output_tag=f"{tag.name}.Output",
            from_members=True,
            source=f"decorated members of {tag.name}",
            comment=tag.comment,
        )
    return blocks


def _find_scp_calls(db: IgnitionTagDB) -> List[RungRef]:
    return [r for r in db.rungs
            if r.instruction.upper() in _SCP_INSTRUCTIONS and len(r.operands) >= 6]


def _scp_ranges(rung: RungRef) -> Dict[str, Optional[float]]:
    """Extract In/InMin/InMax/ScMin/ScMax/Out from an SCP-style call's operands."""
    ops = rung.operands
    return {
        "input_tag": ops[0],
        "input_min": _to_float(ops[1]),
        "input_max": _to_float(ops[2]),
        "scaled_min": _to_float(ops[3]),
        "scaled_max": _to_float(ops[4]),
        "output_tag": ops[5],
    }


def _build_blocks(db: IgnitionTagDB) -> List[ScalingBlock]:
    """Collect member-declared blocks and SCP-rung blocks, merging by tag reference."""
    member_blocks = _find_member_blocks(db)
    blocks: List[ScalingBlock] = list(member_blocks.values())

    for rung in _find_scp_calls(db):
        r = _scp_ranges(rung)
        # Does this SCP write/read a known member-block? (e.g. SCP(..., Blk.Output))
        target = None
        for operand in (r["output_tag"], r["input_tag"]):
            base = operand.split(".")[0].split("[")[0]
            if base in member_blocks:
                target = member_blocks[base]
                break
        if target is not None:
            # Attach wiring; use SCP constants when the member block is unpopulated.
            target.input_tag = target.input_tag or r["input_tag"]
            if _all_zero(target):
                target.input_min, target.input_max = r["input_min"], r["input_max"]
                target.scaled_min, target.scaled_max = r["scaled_min"], r["scaled_max"]
                target.source = (f"wired SCP constants (rung {rung.rung_number} "
                                 f"of {rung.routine}); block members were all-zero")
            continue
        # Standalone SCP block -> its own analog point.
        blocks.append(ScalingBlock(
            name=r["input_tag"].split(".")[0],
            input_min=r["input_min"], input_max=r["input_max"],
            scaled_min=r["scaled_min"], scaled_max=r["scaled_max"],
            input_tag=r["input_tag"], output_tag=r["output_tag"],
            from_members=False,
            source=f"SCP instruction (rung {rung.rung_number} of {rung.routine})",
        ))
    return blocks


def _classify_direction(block: ScalingBlock) -> str:
    """Return "input" or "output" for a scaling block.

    Primary signal: analog role tokens in the block/wired tag names. Tiebreaker:
    the raw/counts side has the larger magnitude, so if the scaled side is
    count-like it is an output (engineering feeds .Input), and vice-versa.
    """
    combined = f"{block.name} {block.input_tag} {block.output_tag}"
    has_out = bool(_OUTPUT_ROLE_RE.search(combined))
    has_in = bool(_INPUT_ROLE_RE.search(combined))
    if has_out and not has_in:
        return "output"
    if has_in and not has_out:
        return "input"
    # Magnitude tiebreaker.
    if _count_like(block.scaled_max) and not _count_like(block.input_max):
        return "output"
    if _count_like(block.input_max) and not _count_like(block.scaled_max):
        return "input"
    # Default: treat as input (the common analog-sensor case).
    return "input"


def _feed_tag_for_input(block: ScalingBlock, db: IgnitionTagDB) -> str:
    """Find the tag feeding a block's ``.Input`` by tracing rung wiring."""
    if block.input_tag and block.input_tag.split(".")[0] != block.name:
        return block.input_tag
    input_ref = f"{block.name}.Input"
    for rung in db.calls_with_operand(input_ref):
        for op in rung.operands:
            base = op.split(".")[0].split("[")[0]
            if base == block.name or _to_float(op) is not None:
                continue
            return op
    return ""


def _downstream_consumer(block: ScalingBlock, db: IgnitionTagDB) -> str:
    """Find an addressable tag that consumes a block's ``.Output`` (downstream PV)."""
    output_ref = f"{block.name}.Output"
    for rung in db.calls_with_operand(output_ref):
        for op in rung.operands:
            base = op.split(".")[0].split("[")[0]
            if base == block.name or _to_float(op) is not None:
                continue
            if db.is_accessible(op):
                return op
    return ""


def _guess_unit(name: str, comment: str) -> str:
    text = f"{name} {comment}".lower()
    for keyword, unit in _UNIT_KEYWORDS:
        if keyword in text:
            return unit
    return ""


def _point_for_block(block: ScalingBlock, db: IgnitionTagDB) -> Dict[str, object]:
    """Turn one resolved scaling block into a per-point result dict."""
    direction = _classify_direction(block)
    unit = _guess_unit(f"{block.name} {block.input_tag} {block.output_tag}", block.comment)

    point: Dict[str, object] = {
        "tag_name": block.name,
        "direction": direction,
        "eng_unit": unit,
        "scaling_source": block.source,
    }

    # Distrust unpopulated ranges (correction #3): a missing endpoint, or all four
    # endpoints zero, means a partial/zeroed export -- flag it, never emit [0, 0].
    range_vals = [block.input_min, block.input_max, block.scaled_min, block.scaled_max]
    unresolved = any(v is None for v in range_vals) or all(v == 0 for v in range_vals)
    if unresolved:
        point.update({
            "recommended_opc_tag": block.output_tag or block.input_tag or block.name,
            "is_engineering_units": False,
            "requires_ignition_scaling": False,
            "eng_low": None, "eng_high": None,
            "scaling_source": "none_found",
            "warning": (f"Scaling ranges for '{block.name}' are unpopulated in this "
                        "export (members all zero and no wired numeric constants "
                        "found). Supply a fully-populated L5X or set ranges manually."),
        })
        return point

    if direction == "output":
        eng_low, eng_high = block.input_min, block.input_max
        feed = _feed_tag_for_input(block, db)
        eng_addressable = bool(feed) and db.is_accessible(feed)
        eng_tag = feed
        raw_side_tag = block.output_tag
    else:  # input
        eng_low, eng_high = block.scaled_min, block.scaled_max
        consumer = _downstream_consumer(block, db)
        eng_tag = consumer or block.output_tag
        eng_addressable = bool(eng_tag) and db.is_accessible(eng_tag)
        raw_side_tag = block.input_tag or block.name

    # Identity conversion: raw range == scaled range means the block performs no
    # real scaling (e.g. a DAC passing mA through). The meaningful engineering range
    # lives elsewhere, so flag it rather than emit a no-op raw->raw "conversion".
    if (block.input_min == block.scaled_min and block.input_max == block.scaled_max):
        point.update({
            "recommended_opc_tag": eng_tag or raw_side_tag or block.name,
            "is_engineering_units": False,
            "requires_ignition_scaling": False,
            "eng_low": None, "eng_high": None,
            "scaling_source": "none_found",
            "warning": (f"Block '{block.name}' has an identity range (raw == scaled); "
                        "it performs no real conversion. The engineering range is "
                        "elsewhere -- verify manually."),
        })
        return point

    # Partial population (correction #3): even with the other side populated, the
    # side we would actually expose can resolve to [0, 0]. Distrust that rather than
    # emit a degenerate range or a raw->[0, 0] "conversion".
    eng_zero = eng_low == 0 and eng_high == 0
    scaled_zero = block.scaled_min == 0 and block.scaled_max == 0
    if (eng_zero if eng_addressable else scaled_zero):
        point.update({
            "recommended_opc_tag": eng_tag or raw_side_tag or block.name,
            "is_engineering_units": False,
            "requires_ignition_scaling": False,
            "eng_low": None, "eng_high": None,
            "scaling_source": "none_found",
            "warning": (f"Scaling for '{block.name}' is only partially populated in "
                        "this export (the exposed side resolves to [0, 0]); verify "
                        "ranges manually."),
        })
        return point

    if eng_addressable:
        # Normal case: PLC already produced an engineering value. Ignition does not
        # re-scale; only engLow/engHigh/engUnit are meaningful downstream.
        point.update({
            "recommended_opc_tag": eng_tag,
            "is_engineering_units": True,
            "requires_ignition_scaling": False,
            "eng_low": eng_low, "eng_high": eng_high,
        })
    else:
        # Raw-hardware fallback: the engineering side is not OPC-addressable, so the
        # sole addressable tag is raw hardware -> Ignition converts raw -> scaled.
        point.update({
            "recommended_opc_tag": raw_side_tag,
            "is_engineering_units": False,
            "requires_ignition_scaling": True,
            "raw_low": block.input_min, "raw_high": block.input_max,
            "scaled_low": block.scaled_min, "scaled_high": block.scaled_max,
            # eng_* deliberately left unset here: the engineering DISPLAY range is a
            # separate concept from the raw->scaled conversion (correction #2).
            "eng_low": None, "eng_high": None,
            "warning": (f"No OPC-addressable engineering tag for '{block.name}'; "
                        "exposing raw hardware and scaling in Ignition."),
        })
    return point


def _stem_of(name: str) -> str:
    """Reduce a tag name to its shared family stem (see ``_STEM_LEADING_STRIP``)."""
    segs = re.split(r"[_\s]+", name)
    segs = [s for s in segs if s]
    i = 0
    while i < len(segs) and segs[i].lower() in _STEM_LEADING_STRIP:
        i += 1
    core = segs[i:]
    while core and core[-1].lower() in _SCALE_SUFFIX_SEGMENTS:
        core.pop()
    return "_".join(core)


def _is_scale_setpoint(entry) -> bool:
    segs = re.split(r"[_\s]+", entry.name)
    return bool(segs) and segs[-1].lower() in _SCALE_SUFFIX_SEGMENTS


def _find_transmitter_points(db: IgnitionTagDB,
                             covered_bases: set) -> List[Dict[str, object]]:
    """Detect process-transmitter analog points with no SCP block.

    Many analog inputs are not scaled by an SCP/SCPLim1 instance but by a companion
    scale-range setpoint tag whose *value* is the engineering full-scale. This finds
    families sharing a stem that contain a raw alias-AI tag and such a setpoint, and
    exposes the engineering PV (preferred) or the raw input, with engineering range
    ``[0, setpoint value]`` -- the engineering value the operator wants in SCADA.
    """
    families: Dict[str, Dict[str, object]] = {}
    for entry in db.opc_addressable_tags():
        stem = _stem_of(entry.name)
        if not stem:
            continue
        fam = families.setdefault(stem, {"raw_ai": None, "scale_sp": None, "pv": None})
        dtype = entry.data_type.upper()
        if _is_scale_setpoint(entry) and _to_float(entry.value) is not None:
            fam["scale_sp"] = entry
        elif _INPUT_ROLE_RE.search(entry.name) and dtype in _RAW_AI_TYPES:
            fam["raw_ai"] = fam["raw_ai"] or entry
        elif (dtype in _ENG_PV_TYPES and not _INPUT_ROLE_RE.search(entry.name)
              and not _OUTPUT_ROLE_RE.search(entry.name)):
            fam["pv"] = fam["pv"] or entry

    points: List[Dict[str, object]] = []
    for stem, fam in families.items():
        scale_sp, raw_ai, pv = fam["scale_sp"], fam["raw_ai"], fam["pv"]
        # Need a scale-range setpoint AND a raw analog input to call it a transmitter.
        if scale_sp is None or raw_ai is None:
            continue
        if raw_ai.name in covered_bases or (pv is not None and pv.name in covered_bases):
            continue

        eng_high = _to_float(scale_sp.value)
        unit = _guess_unit(stem, (pv.comment if pv else raw_ai.comment))
        common = {
            "tag_name": stem,
            "direction": "input",
            "eng_unit": unit,
            "eng_low": 0.0,
            "eng_high": eng_high,
            "scaling_source": (f"engineering scale-range setpoint '{scale_sp.name}'"
                               f"={eng_high:g}"),
        }
        if pv is not None:
            # Preferred: the PLC already computes the engineering value; expose it.
            common.update({
                "recommended_opc_tag": pv.name,
                "is_engineering_units": True,
                "requires_ignition_scaling": False,
            })
        else:
            # Only the raw input is available; its raw->count range is not encoded in
            # the L5X (it lives in the analog module config), so Ignition scaling
            # cannot be fully configured. Expose the raw tag with the engineering
            # display range and flag that the raw range needs manual entry.
            common.update({
                "recommended_opc_tag": raw_ai.name,
                "is_engineering_units": False,
                "requires_ignition_scaling": False,
                "warning": (f"Engineering full-scale {eng_high:g} from '{scale_sp.name}', "
                            f"but the raw count range for '{raw_ai.name}' is not in the "
                            "L5X (analog module config); set rawLow/rawHigh manually."),
            })
        points.append(common)
    return points


def detect_analog_scaling(db: IgnitionTagDB,
                          target_tags: Optional[List[str]] = None) -> List[Dict[str, object]]:
    """Detect scaling for every analog point in ``db`` (optionally filtered).

    Covers two categories: SCP/SCPLim1 scaling blocks (member- or rung-declared) and
    process transmitters scaled by a companion scale-range setpoint tag.
    """
    blocks = _build_blocks(db)
    points = [_point_for_block(b, db) for b in blocks]

    covered_bases = {str(p.get("recommended_opc_tag", "")).split(".")[0] for p in points}
    points.extend(_find_transmitter_points(db, covered_bases))
    points.sort(key=lambda p: str(p.get("tag_name", "")))

    if target_tags:
        wanted = set(target_tags)
        points = [
            p for p in points
            if wanted & {p.get("tag_name"), p.get("recommended_opc_tag")}
            or any(t in str(p.get("recommended_opc_tag", "")) for t in wanted)
        ]
    return points


def extract_analog_scaling(file_path: str,
                           target_tags: Optional[List[str]] = None) -> Dict[str, object]:
    """Public entry point: load a project and detect analog scaling."""
    db = load_tag_db(file_path)
    points = detect_analog_scaling(db, target_tags=target_tags)
    return {
        "success": True,
        "l5x_file": str(db.l5x_path),
        "project_name": db.controller_name,
        "scaled_points_count": len(points),
        "scaled_points": points,
    }
