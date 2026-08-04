"""Parsed-XML semantic inventory and parity reporting for Logix L5X files."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def _attributes(element: ET.Element, names: Iterable[str]) -> tuple[tuple[str, str], ...]:
    return tuple((name, element.get(name, "")) for name in names)


def _description_inventory(root: ET.Element) -> Dict[str, str]:
    descriptions: Dict[str, str] = {}

    def walk(element: ET.Element, context: tuple[str, ...]) -> None:
        segment = element.tag
        name = element.get("Name")
        if element.tag == "Module":
            segment = f"Module:{name or '?'}"
        elif element.tag == "Connection":
            segment = f"Connection:{name or '?'}"
        elif element.tag == "Tag":
            segment = f"Tag:{name or '?'}"
        elif element.tag in {"Program", "Routine", "DataType", "AddOnInstructionDefinition"}:
            segment = f"{element.tag}:{name or '?'}"
        elif element.tag in {"ConfigTag", "InputTag", "OutputTag"}:
            segment = element.tag

        next_context = context + (segment,)
        description = element.find("./Description")
        if description is not None and _text(description):
            descriptions["/".join(next_context)] = _text(description)
        for child in element:
            if child.tag != "Description":
                walk(child, next_context)

    controller = root.find("./Controller")
    if controller is not None:
        walk(controller, tuple())
    return descriptions


def inventory_l5x(path: str | Path) -> Dict[str, Dict[Any, Any]]:
    """Return stable, semantic maps instead of formatting-sensitive XML text."""
    root = ET.parse(path).getroot()
    controller = root.find("./Controller")
    if controller is None:
        raise ValueError(f"L5X has no Controller element: {path}")

    inventory: Dict[str, Dict[Any, Any]] = {
        "controller_tags": {},
        "programs": {},
        "routines": {},
        "rungs": {},
        "rung_comments": {},
        "operand_comments": {},
        "descriptions": _description_inventory(root),
        "data_types": {},
        "aois": {},
        "modules": {},
        "tasks": {},
    }

    for tag in controller.findall("./Tags/Tag"):
        name = tag.get("Name", "")
        inventory["controller_tags"][name] = _attributes(
            tag, ("TagType", "DataType", "Dimensions", "Radix", "AliasFor", "ExternalAccess")
        )
        for comment in tag.findall("./Comments/Comment"):
            inventory["operand_comments"][(name, comment.get("Operand", ""))] = _text(comment)

    for program in controller.findall("./Programs/Program"):
        program_name = program.get("Name", "")
        inventory["programs"][program_name] = _attributes(
            program, ("MainRoutineName", "FaultRoutineName", "Disabled")
        )
        for routine in program.findall("./Routines/Routine"):
            routine_name = routine.get("Name", "")
            routine_key = (program_name, routine_name)
            inventory["routines"][routine_key] = routine.get("Type", "")
            for rung in routine.findall("./RLLContent/Rung"):
                rung_key = routine_key + (rung.get("Number", ""),)
                inventory["rungs"][rung_key] = _text(rung.find("./Text"))
                comment_text = _text(rung.find("./Comment"))
                if comment_text:
                    inventory["rung_comments"][rung_key] = comment_text

    for data_type in controller.findall("./DataTypes/DataType"):
        inventory["data_types"][data_type.get("Name", "")] = _attributes(
            data_type, ("Family", "Class")
        )
    for aoi in controller.findall("./AddOnInstructionDefinitions/AddOnInstructionDefinition"):
        inventory["aois"][aoi.get("Name", "")] = _attributes(aoi, ("Revision", "SoftwareRevision"))
    for index, module in enumerate(controller.findall("./Modules/Module")):
        key = module.get("Name") or f"#{index}"
        inventory["modules"][key] = _attributes(
            module,
            ("CatalogNumber", "Vendor", "ProductType", "ProductCode", "Major", "Minor", "ParentModule", "ParentModPortId"),
        )
    for task in controller.findall("./Tasks/Task"):
        inventory["tasks"][task.get("Name", "")] = _attributes(
            task, ("Type", "Rate", "Priority", "Watchdog")
        )
    return inventory


def _json_key(key: Any) -> str:
    return "/".join(str(part) for part in key) if isinstance(key, tuple) else str(key)


def _compare_maps(reference: Mapping[Any, Any], generated: Mapping[Any, Any]) -> Dict[str, Any]:
    reference_keys = set(reference)
    generated_keys = set(generated)
    common = reference_keys & generated_keys
    changed = [key for key in common if reference[key] != generated[key]]
    return {
        "reference_count": len(reference),
        "generated_count": len(generated),
        "matched_count": sum(reference[key] == generated[key] for key in common),
        "losses": sorted(_json_key(key) for key in reference_keys - generated_keys),
        "extras": sorted(_json_key(key) for key in generated_keys - reference_keys),
        "changed": sorted(_json_key(key) for key in changed),
        "changed_details": [
            {
                "key": _json_key(key),
                "reference": reference[key],
                "generated": generated[key],
            }
            for key in sorted(changed, key=_json_key)
        ],
    }


def compare_l5x(generated_path: str | Path, reference_path: str | Path) -> Dict[str, Any]:
    """Compare generated L5X to a matching Studio export and report every loss."""
    generated = inventory_l5x(generated_path)
    reference = inventory_l5x(reference_path)
    categories = {
        category: _compare_maps(reference[category], generated[category])
        for category in reference
    }
    has_differences = any(
        report["losses"] or report["extras"] or report["changed"]
        for report in categories.values()
    )
    logic_categories = ("routines", "rungs", "rung_comments", "operand_comments")
    logic_parity = all(
        not categories[name]["losses"]
        and not categories[name]["extras"]
        and not categories[name]["changed"]
        for name in logic_categories
    )
    return {
        "status": "differences" if has_differences else "match",
        "logic_parity": logic_parity,
        "import_safe": not has_differences,
        "generated_path": str(Path(generated_path)),
        "reference_path": str(Path(reference_path)),
        "categories": categories,
    }
