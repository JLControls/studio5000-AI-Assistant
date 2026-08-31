"""
Final-review fix: AOI identifiers get no bilingual treatment anywhere.

ModelGenerator._element() sets ``head = instr.instruction`` for block-shaped
elements (timer/counter/compare/math/move/AOI/other). For an AOI call block,
``head`` IS the AOI's own identifier (e.g. "Pompa1"), so — the same way
tag/program/routine identifiers are translated elsewhere (html_generator._id
/ _idj) — it must become bilingual-capable: a plain string normally, or an
{"en": ..., "it": ...} dict when the AOI's name is Italian and an
``aoi_id_display`` translation map (html_generator._idj() output, keyed by
AOI definition name) is supplied.

Built-in instruction mnemonics (TON, ADD, JSR, ...) are never looked up in
``aoi_id_display`` (it is only consulted for InstructionType.AOI blocks), so
their block head stays byte-identical to the pre-fix behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).parent.resolve()
_DOCUMENTER_DIR = _TESTS_DIR.parent
if str(_DOCUMENTER_DIR) not in sys.path:
    sys.path.insert(0, str(_DOCUMENTER_DIR))

from l5x_documenter.ladder_to_dot import convert_rung_to_model, ModelGenerator  # noqa: E402

_IT_DISPLAY = {"en": "Pompa1 (Pump1)", "it": "Pompa1"}


def test_aoi_head_becomes_bilingual_dict_when_display_map_provided():
    """An AOI call block's 'head' becomes the {en,it} dict from aoi_id_display."""
    model = convert_rung_to_model(
        "Pompa1(Motor1);",
        aoi_id_display={"Pompa1": _IT_DISPLAY},
    )
    assert len(model["out"]) == 1, "AOI call should be right-justified as an output"
    head = model["out"][0]["head"]
    assert isinstance(head, dict), f"expected {{en,it}} dict, got {type(head).__name__}: {head!r}"
    assert head == _IT_DISPLAY


def test_aoi_head_stays_plain_string_when_no_display_map():
    """With no aoi_id_display (non-bilingual doc), head stays the raw identifier string."""
    model = convert_rung_to_model("Pompa1(Motor1);")
    head = model["out"][0]["head"]
    assert isinstance(head, str)
    assert head == "Pompa1"


def test_aoi_head_stays_plain_string_for_english_aoi_even_with_display_map():
    """An English AOI's display value is a plain string (en == it), matching _idj()."""
    model = convert_rung_to_model(
        "ValveCtrl(Valve1);",
        aoi_id_display={"ValveCtrl": "ValveCtrl"},
    )
    head = model["out"][0]["head"]
    assert isinstance(head, str)
    assert head == "ValveCtrl"


def test_non_aoi_block_head_unaffected_by_display_map():
    """A non-AOI block (e.g. TON) never consults aoi_id_display, even if it
    happens to share a key — head stays the raw instruction mnemonic string."""
    model = convert_rung_to_model(
        "TON(Timer1,1000,0);",
        aoi_id_display={"TON": {"en": "should never be used", "it": "TON"}},
    )
    head = model["out"][0]["head"]
    assert head == "TON"


def test_element_level_aoi_head_lookup():
    """Unit-level check directly on ModelGenerator, mirroring the _desc() tests."""
    from l5x_documenter.ladder_to_dot import LadderParser

    parser = LadderParser()
    rung = parser.parse_rung("Pompa1(Motor1);", 0, "")
    gen = ModelGenerator(aoi_id_display={"Pompa1": _IT_DISPLAY})
    result = gen.generate(rung)
    assert result["out"][0]["head"] == _IT_DISPLAY


def test_element_level_aoi_head_defaults_to_raw_name_when_key_absent():
    """An AOI name absent from aoi_id_display falls back to the raw instruction
    string (matches dict.get(head, head) fallback)."""
    from l5x_documenter.ladder_to_dot import LadderParser

    parser = LadderParser()
    rung = parser.parse_rung("Pompa1(Motor1);", 0, "")
    gen = ModelGenerator(aoi_id_display={})
    result = gen.generate(rung)
    assert result["out"][0]["head"] == "Pompa1"
