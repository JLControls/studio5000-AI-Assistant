"""Tests for the deterministic L5X structural parser backing issue #9.

The parser must enumerate programs / routines / UDTs by walking the XML tree,
keyed by ``(program, routine)`` so same-named routines in different programs are
counted independently, and it must not miss encrypted (``EncodedData``) routines.
"""
import os

from l5x_analyzer.l5x_structure import parse_l5x_structure, merge_structures

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
