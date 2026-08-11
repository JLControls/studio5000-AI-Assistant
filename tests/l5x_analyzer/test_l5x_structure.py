"""Tests for the deterministic L5X structural parser backing issue #9.

The parser must enumerate programs / routines / UDTs by walking the XML tree,
keyed by ``(program, routine)`` so same-named routines in different programs are
counted independently, and it must not miss encrypted (``EncodedData``) routines.
"""
import os

from l5x_analyzer.l5x_structure import (
    merge_structures,
    parse_l5x_structure,
    summarize_structure,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "multiprogram.L5X")


def test_parses_all_three_programs():
    structure = parse_l5x_structure(FIXTURE)
    assert sorted(structure["programs"]) == ["Alpha", "Beta", "Gamma"]


def test_controller_name_is_captured():
    structure = parse_l5x_structure(FIXTURE)
    assert structure["controller"] == "TestCtl"


def test_duplicate_routine_names_counted_per_program():
    structure = parse_l5x_structure(FIXTURE)
    keys = {(r["program"], r["name"]) for r in structure["routines"]}
    assert ("Alpha", "Logic") in keys
    assert ("Gamma", "Logic") in keys
    # Alpha/Logic, Alpha/Init, Beta/MainRoutine, Beta/Secret, Gamma/Logic
    assert len(structure["routines"]) == 5


def test_encoded_routine_is_counted():
    structure = parse_l5x_structure(FIXTURE)
    secret = [r for r in structure["routines"] if r["name"] == "Secret"]
    assert len(secret) == 1
    assert secret[0]["program"] == "Beta"
    assert secret[0]["encoded"] is True


def test_user_udt_is_counted():
    structure = parse_l5x_structure(FIXTURE)
    assert structure["udts"] == ["MyUDT"]


def test_add_on_defined_types_are_enumerated():
    # Each AddOnInstructionDefinition also defines an Add-On-Defined data type;
    # these are the ones we keep missing when only User UDTs are counted.
    structure = parse_l5x_structure(FIXTURE)
    assert structure["add_on_instructions"] == ["Scale"]


def test_aoi_internal_routine_not_counted_as_program_routine():
    # The AOI "Scale" contains a routine named "Logic"; it must not leak into
    # the program routine inventory.
    structure = parse_l5x_structure(FIXTURE)
    programs_of_logic = {r["program"] for r in structure["routines"] if r["name"] == "Logic"}
    assert programs_of_logic == {"Alpha", "Gamma"}
    assert "Scale" not in {r["program"] for r in structure["routines"]}


def test_modules_are_enumerated_with_catalog_and_slot():
    structure = parse_l5x_structure(FIXTURE)
    by_name = {m["name"]: m for m in structure["modules"]}
    assert set(by_name) == {"Local", "AI_Module"}
    assert by_name["AI_Module"]["catalog"] == "5069-IF8/A"
    assert by_name["AI_Module"]["slot"] == "2"


def test_summarize_includes_aoi_and_module_counts():
    structure = parse_l5x_structure(FIXTURE)
    summary = summarize_structure(structure)
    assert summary["add_on_instruction_count"] == 1
    assert summary["module_count"] == 2


def test_merge_dedupes_aois_and_modules():
    structure = parse_l5x_structure(FIXTURE)
    merged = merge_structures([structure, structure])
    assert merged["add_on_instructions"] == ["Scale"]
    assert len(merged["modules"]) == 2


def test_merge_keeps_distinct_nameless_modules():
    # ACD->L5X conversion can leave local rack modules with no Name; they are
    # distinguished only by slot and must not collapse into a single entry.
    structure = {
        "controller": "C",
        "programs": [],
        "routines": [],
        "udts": [],
        "add_on_instructions": [],
        "modules": [
            {"name": None, "catalog": "5069-IF8/A", "parent": "Local", "slot": "2"},
            {"name": None, "catalog": "5069-OF4/A", "parent": "Local", "slot": "3"},
        ],
    }
    merged = merge_structures([structure])
    assert len(merged["modules"]) == 2


def test_merge_unions_programs_and_dedupes_routines():
    structure = parse_l5x_structure(FIXTURE)
    # Merging a structure with itself must not double-count anything.
    merged = merge_structures([structure, structure])
    assert sorted(merged["programs"]) == ["Alpha", "Beta", "Gamma"]
    assert len(merged["routines"]) == 5
    assert merged["udts"] == ["MyUDT"]


def test_merge_combines_distinct_files():
    file_a = {
        "controller": "TestCtl",
        "programs": ["Alpha"],
        "routines": [{"program": "Alpha", "name": "Logic", "type": "RLL", "encoded": False}],
        "udts": ["MyUDT"],
    }
    file_b = {
        "controller": "TestCtl",
        "programs": ["Beta"],
        "routines": [{"program": "Beta", "name": "Logic", "type": "RLL", "encoded": False}],
        "udts": ["OtherUDT"],
    }
    merged = merge_structures([file_a, file_b])
    assert sorted(merged["programs"]) == ["Alpha", "Beta"]
    assert len(merged["routines"]) == 2
    assert sorted(merged["udts"]) == ["MyUDT", "OtherUDT"]
