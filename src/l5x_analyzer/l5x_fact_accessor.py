"""Deterministic L5X fact accessors (issue #28).

Three structural, vector-free reads over an exported L5X. They surface facts
that already exist in the file but were previously only reachable by hand-parsing
the XML:

- :func:`get_tag_value` — a tag's configured value(s) from the decorated
  ``<Data>`` tree (scalars, UDT members, arrays), respecting radix and scope.
- :func:`describe_aoi` — an AOI's parameters in invocation (document) order.
- :func:`decode_aoi_call` — a rung's AOI-call operands mapped onto those
  parameters, treating operand 0 as the backing instance and binding the rest
  positionally to the required (callable) parameters.

These are exact structural reads: no vector database, no embeddings, no ACD
decode. Missing/encrypted data is reported explicitly rather than defaulting to
zero, so callers (#26 where-used, #27 liveness) can trust the values.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .aoi_logic_inspector import extract_ordered_parameters
from .rll_parser import find_calls as _find_calls
from .rll_parser import split_operands as _split_operands

# Operands that stand in for an unwired parameter position rather than a real
# tag/immediate. Kept narrow so real tags are never misread as placeholders.
_PLACEHOLDER_OPERANDS = {"NA", "?"}

# Implicit AOI members that never appear in a ladder invocation's operand list.
_IMPLICIT_AOI_PARAMS = {"EnableIn", "EnableOut"}


def _load_controller(l5x_path: str | Path) -> Tuple[Optional[ET.Element], Optional[ET.Element], Optional[str]]:
    """Parse an L5X and return ``(controller_elem, root_elem, error)``."""
    try:
        root = ET.parse(str(l5x_path)).getroot()
    except Exception as exc:  # malformed XML, missing file, etc.
        return None, None, f"Failed to parse L5X '{l5x_path}': {exc}"
    controller = root.find("Controller")
    if controller is None:
        controller = root.find(".//Controller")
    if controller is None:
        return None, root, "No <Controller> element found in L5X."
    return controller, root, None


def _coerce(raw: Optional[str], radix: Optional[str], data_type: Optional[str]) -> Any:
    """Coerce a decorated ``Value`` string into a Python scalar when unambiguous.

    Float/Decimal values become ``float``/``int``; non-decimal radices
    (Hex/Binary/ASCII/…) are left as their original string so no information is
    lost.
    """
    if raw is None:
        return None
    dt = (data_type or "").upper()
    rx = radix or ""
    if rx == "Float" or dt in ("REAL", "LREAL"):
        try:
            return float(raw)
        except ValueError:
            return raw
    if rx in ("", "Decimal"):
        try:
            return int(raw)
        except ValueError:
            return raw
    # Hex / Binary / Octal / ASCII / DateTime — keep the exact stored text.
    return raw


def _parse_node(elem: ET.Element,
                inherited_radix: Optional[str] = None,
                inherited_type: Optional[str] = None) -> Dict[str, Any]:
    """Parse a decorated data element into a typed node tree.

    Nodes are one of ``scalar`` (leaf value), ``struct`` (named members), or
    ``array`` (ordered elements). Array elements inherit the array's radix/type
    because they do not repeat those attributes.
    """
    tag = elem.tag
    if tag in ("DataValue", "DataValueMember"):
        radix = elem.get("Radix", inherited_radix)
        data_type = elem.get("DataType", inherited_type)
        return {
            "kind": "scalar",
            "data_type": data_type,
            "radix": radix,
            "value": _coerce(elem.get("Value"), radix, data_type),
        }
    if tag in ("Structure", "StructureMember"):
        members: Dict[str, Dict[str, Any]] = {}
        for child in list(elem):
            name = child.get("Name")
            if name is None:
                continue
            members[name] = _parse_node(child)
        return {
            "kind": "struct",
            "data_type": elem.get("DataType"),
            "radix": None,
            "members": members,
        }
    if tag in ("Array", "ArrayMember"):
        radix = elem.get("Radix", inherited_radix)
        data_type = elem.get("DataType", inherited_type)
        elements = [
            _parse_node(e, inherited_radix=radix, inherited_type=data_type)
            for e in elem.findall("Element")
        ]
        return {
            "kind": "array",
            "data_type": data_type,
            "radix": radix,
            "dimensions": elem.get("Dimensions"),
            "elements": elements,
        }
    if tag == "Element":
        # Scalar array element carries Value; struct array element wraps a Structure.
        struct = elem.find("Structure")
        if struct is not None:
            return _parse_node(struct)
        return {
            "kind": "scalar",
            "data_type": inherited_type,
            "radix": inherited_radix,
            "value": _coerce(elem.get("Value"), inherited_radix, inherited_type),
        }
    # Unknown element: expose it as an opaque scalar rather than crashing.
    return {"kind": "scalar", "data_type": elem.get("DataType"), "radix": elem.get("Radix"),
            "value": elem.get("Value")}


def _to_value(node: Dict[str, Any]) -> Any:
    """Collapse a node tree into plain values (scalar / dict / list)."""
    if node["kind"] == "scalar":
        return node["value"]
    if node["kind"] == "struct":
        return {name: _to_value(child) for name, child in node["members"].items()}
    if node["kind"] == "array":
        return [_to_value(e) for e in node["elements"]]
    return None


def _parse_member_path(member: str) -> List[Tuple[str, Any]]:
    """Tokenize a member path like ``Cfg.Min`` or ``arr[2].x`` into steps."""
    tokens: List[Tuple[str, Any]] = []
    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]", member):
        if m.group(1) is not None:
            tokens.append(("name", m.group(1)))
        else:
            tokens.append(("index", int(m.group(2))))
    return tokens


def _navigate(node: Dict[str, Any], tokens: List[Tuple[str, Any]]) -> Optional[Dict[str, Any]]:
    cur = node
    for kind, val in tokens:
        if kind == "name":
            if cur["kind"] != "struct" or val not in cur["members"]:
                return None
            cur = cur["members"][val]
        else:  # index
            if cur["kind"] != "array" or val >= len(cur["elements"]):
                return None
            cur = cur["elements"][val]
    return cur


def _decorated_data(tag_elem: ET.Element) -> Optional[ET.Element]:
    for data in tag_elem.findall("Data"):
        if data.get("Format") == "Decorated":
            return data
    return None


def get_tag_value(l5x_path: str | Path,
                  tag_name: str,
                  member: Optional[str] = None,
                  program_name: Optional[str] = None) -> Dict[str, Any]:
    """Return a tag's configured value(s) from decorated L5X data.

    Resolution is scope-aware: without ``program_name`` a tag that exists at
    both controller and program scope (or in several programs) is an explicit
    ambiguity error rather than an arbitrary pick. ``member`` addresses a nested
    UDT member (``Cfg.Min``) or array element (``[1]``); when omitted on a
    structure/array the full value tree is returned instead of a flattened
    string. Alias tags return their target without inventing a value, and a tag
    with no decorated data is reported as unsupported rather than defaulting to
    zero.
    """
    controller, _root, error = _load_controller(l5x_path)
    if error:
        return {"success": False, "error": error}

    candidates: List[Tuple[str, Optional[str], ET.Element]] = []
    ctl_tags = controller.find("Tags")
    if ctl_tags is not None:
        for t in ctl_tags.findall("Tag"):
            if t.get("Name") == tag_name:
                candidates.append(("controller", None, t))
    for prog in controller.findall("Programs/Program"):
        pname = prog.get("Name")
        ptags = prog.find("Tags")
        if ptags is None:
            continue
        for t in ptags.findall("Tag"):
            if t.get("Name") == tag_name:
                candidates.append(("program", pname, t))

    if program_name:
        scoped = [c for c in candidates if c[1] == program_name]
        if not scoped:
            return {"success": False,
                    "error": f"Tag '{tag_name}' not found in program '{program_name}'."}
        scope, program, tag_elem = scoped[0]
    else:
        if not candidates:
            return {"success": False, "error": f"Tag '{tag_name}' not found."}
        if len(candidates) > 1:
            where = ", ".join(
                "controller" if c[0] == "controller" else f"program '{c[1]}'"
                for c in candidates
            )
            return {"success": False,
                    "error": (f"Tag '{tag_name}' is ambiguous — defined in {where}. "
                              "Pass program_name to disambiguate.")}
        scope, program, tag_elem = candidates[0]

    base = {
        "success": True,
        "tag": tag_name,
        "scope": scope,
        "program": program,
        "requested_member": member,
        "data_type": tag_elem.get("DataType"),
        "radix": tag_elem.get("Radix"),
    }

    if tag_elem.get("TagType") == "Alias":
        base.update({
            "is_alias": True,
            "alias_for": tag_elem.get("AliasFor"),
            "value": None,
            "note": "Alias tag — resolve the target's value at its own scope.",
        })
        return base

    decorated = _decorated_data(tag_elem)
    if decorated is None or len(list(decorated)) == 0:
        return {"success": False,
                "tag": tag_name,
                "scope": scope,
                "program": program,
                "error": (f"Tag '{tag_name}' has no decorated data in this L5X "
                          "(only non-Decorated or no stored value). Configured value "
                          "unavailable from this export; ACD data-table decode is #23.")}

    node = _parse_node(list(decorated)[0])
    if member:
        target = _navigate(node, _parse_member_path(member))
        if target is None:
            return {"success": False,
                    "tag": tag_name,
                    "error": f"Member '{member}' not found in tag '{tag_name}'."}
    else:
        target = node

    base["data_type"] = target.get("data_type") or base["data_type"]
    base["radix"] = target.get("radix")
    base["value"] = _to_value(target)
    return base


def describe_aoi(l5x_path: str | Path, aoi_name: str) -> Dict[str, Any]:
    """Return an AOI's ordered parameter definition.

    Parameters keep document order (the positional calling contract) and carry
    ``usage`` / ``data_type`` / ``required`` / ``visible`` / ``dimensions`` /
    ``description`` — everything :func:`decode_aoi_call` and #26 need to label an
    invocation's operands with real names and read/write direction.
    """
    _controller, root, error = _load_controller(l5x_path)
    if error and root is None:
        return {"success": False, "error": error}

    for aoi in root.iter("AddOnInstructionDefinition"):
        if aoi.get("Name") == aoi_name:
            desc_el = aoi.find("Description")
            description = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
            return {
                "success": True,
                "aoi": aoi_name,
                "description": description,
                "parameters": extract_ordered_parameters(aoi),
            }
    return {"success": False, "error": f"Add-On Instruction '{aoi_name}' not found."}


def _resolve_routine(controller: ET.Element,
                     routine_name: str,
                     program_name: Optional[str]) -> Tuple[Optional[str], Optional[ET.Element], Optional[str]]:
    """Resolve exactly one ``(program, routine)`` or return an error string."""
    matches: List[Tuple[str, ET.Element]] = []
    for prog in controller.findall("Programs/Program"):
        pname = prog.get("Name")
        if program_name and pname != program_name:
            continue
        for routine in prog.findall("Routines/Routine"):
            if routine.get("Name") == routine_name:
                matches.append((pname, routine))
    if not matches:
        scope = f" in program '{program_name}'" if program_name else ""
        return None, None, f"Routine '{routine_name}' not found{scope}."
    if len(matches) > 1:
        progs = ", ".join(f"'{p}'" for p, _ in matches)
        return None, None, (f"Routine '{routine_name}' is ambiguous — defined in programs "
                            f"{progs}. Pass program_name to disambiguate.")
    return matches[0][0], matches[0][1], None


def decode_aoi_call(l5x_path: str | Path,
                    routine_name: str,
                    rung_number: int,
                    program_name: Optional[str] = None,
                    aoi_name: Optional[str] = None) -> Dict[str, Any]:
    """Decode a rung's AOI invocation(s) into operand → parameter bindings.

    Operand 0 is the AOI backing-instance tag; the remaining operands bind
    positionally to the required (callable) parameters in document order,
    excluding the implicit ``EnableIn``/``EnableOut`` members. ``NA``/placeholder
    operands are preserved as explicit unbound positions, and an operand count
    that does not match the callable-parameter count is flagged rather than
    silently shifting bindings. A rung with multiple AOI calls returns them all
    (optionally filtered by ``aoi_name``).
    """
    controller, root, error = _load_controller(l5x_path)
    if error:
        return {"success": False, "error": error}

    program, routine, rerror = _resolve_routine(controller, routine_name, program_name)
    if rerror:
        return {"success": False, "error": rerror}

    rung_elem = None
    for r in routine.findall(".//Rung"):
        if r.get("Number") == str(rung_number):
            rung_elem = r
            break
    if rung_elem is None:
        return {"success": False,
                "error": f"Rung {rung_number} not found in routine '{routine_name}'."}

    text_el = rung_elem.find("Text")
    text = (text_el.text or "") if text_el is not None else ""

    aoi_defs = {a.get("Name"): a for a in root.iter("AddOnInstructionDefinition")}

    calls: List[Dict[str, Any]] = []
    for mnemonic, operands, span in _find_calls(text):
        if mnemonic not in aoi_defs:
            continue
        if aoi_name and mnemonic != aoi_name:
            continue

        params = extract_ordered_parameters(aoi_defs[mnemonic])
        callable_params = [
            p for p in params
            if p["required"] and p["name"] not in _IMPLICIT_AOI_PARAMS
        ]

        backing = operands[0] if operands else None
        arg_operands = operands[1:]

        bindings: List[Dict[str, Any]] = []
        for idx, param in enumerate(callable_params):
            operand = arg_operands[idx] if idx < len(arg_operands) else None
            bindings.append({
                "argument_position": idx + 1,
                "operand": operand,
                "param_name": param["name"],
                "usage": param["usage"],
                "data_type": param["data_type"],
                "required": param["required"],
                "placeholder": operand in _PLACEHOLDER_OPERANDS,
                "bound": operand is not None,
            })

        extra_operands = arg_operands[len(callable_params):]
        calls.append({
            "aoi": mnemonic,
            "backing_tag": backing,
            "text": span,
            "bindings": bindings,
            "operand_count": len(arg_operands),
            "callable_param_count": len(callable_params),
            "mismatch": len(arg_operands) != len(callable_params),
            "extra_operands": extra_operands,
        })

    return {
        "success": True,
        "program": program,
        "routine": routine_name,
        "rung": rung_number,
        "calls": calls,
    }
