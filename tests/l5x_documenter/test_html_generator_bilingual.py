"""
Tests for Task 3: bilingual HTML emission in html_generator.py.

All tests run fully offline (use_online=False; no network).
Run with: python -m pytest tests/ -q  (from the documenter directory)
"""

from __future__ import annotations

import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Ensure documenter dir is on sys.path
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).parent.resolve()
_DOCUMENTER_DIR = _TESTS_DIR.parent
if str(_DOCUMENTER_DIR) not in sys.path:
    sys.path.insert(0, str(_DOCUMENTER_DIR))


# ---------------------------------------------------------------------------
# Minimal fixture helpers
# ---------------------------------------------------------------------------

def _make_controller(
    name: str = "TestController",
    programs: list | None = None,
    controller_tags: list | None = None,
    data_types: list | None = None,
    add_on_instructions: list | None = None,
    modules: list | None = None,
):
    """Build a minimal Controller dataclass for testing."""
    from l5x_documenter.parser import (
        Controller, Program, Routine, Rung, Tag, TagUsage,
        UserDataType, AddOnInstruction, Module,
    )

    if programs is None:
        programs = []
    if controller_tags is None:
        controller_tags = []
    if data_types is None:
        data_types = []
    if add_on_instructions is None:
        add_on_instructions = []
    if modules is None:
        modules = []

    return Controller(
        name=name,
        processor_type="1756-L73",
        major_rev=33,
        minor_rev=11,
        software_revision="33.00",
        export_date="2025-01-01",
        programs=programs,
        controller_tags=controller_tags,
        data_types=data_types,
        add_on_instructions=add_on_instructions,
        modules=modules,
        comm_path="",
        ethernet_mode="",
    )


def _make_program(name: str, routines: list | None = None, local_tags: list | None = None):
    from l5x_documenter.parser import Program
    return Program(
        name=name,
        main_routine="Main",
        routines=routines or [],
        local_tags=local_tags or [],
    )


def _make_routine(name: str, rungs: list | None = None):
    from l5x_documenter.parser import Routine
    return Routine(name=name, routine_type="RLL", rungs=rungs or [])


def _make_rung(number: int = 0, text: str = "NOP();", comment: str = ""):
    from l5x_documenter.parser import Rung
    return Rung(number=number, rung_type="N", text=text, comment=comment)


def _make_tag(name: str, description: str = ""):
    from l5x_documenter.parser import Tag
    return Tag(name=name, data_type="BOOL", scope="Controller", description=description)


def _extract_ladder_data(html_content: str) -> dict:
    """Parse window.__LADDER_DATA__ = {...}; from the HTML output."""
    match = re.search(
        r'window\.__LADDER_DATA__\s*=\s*(\{.*?\});\s*\n',
        html_content,
        re.DOTALL,
    )
    assert match, "window.__LADDER_DATA__ not found in HTML"
    return json.loads(match.group(1))


# ---------------------------------------------------------------------------
# Italian fixture data
# ---------------------------------------------------------------------------

ITALIAN_PROG_NAME = "Nastro1"           # Italian: nastro → conveyor
ENGLISH_PROG_NAME = "ConveyorControl"   # English
ITALIAN_DESC = "motore in marcia"       # Italian → "motor running"
ENGLISH_DESC = "Motor running"          # English (no translation)
ITALIAN_ROUTINE_NAME = "Avviamento"     # Italian: avviamento → startup (in glossary?)
ENGLISH_ROUTINE_NAME = "MainLogic"      # English


def _make_bilingual_controller():
    """
    Controller with:
    - One Italian-named program ('Nastro1') containing an Italian routine name
    - One Italian-described controller tag
    - One English-described controller tag
    """
    italian_routine = _make_routine(
        name=ITALIAN_ROUTINE_NAME,
        rungs=[_make_rung(0, "NOP();", "Avvio motore nastro")]
    )
    italian_program = _make_program(
        name=ITALIAN_PROG_NAME,
        routines=[italian_routine],
    )
    english_routine = _make_routine(name=ENGLISH_ROUTINE_NAME, rungs=[_make_rung(0)])
    english_program = _make_program(name=ENGLISH_PROG_NAME, routines=[english_routine])

    it_tag = _make_tag("NASTRO_TAG", description=ITALIAN_DESC)
    en_tag = _make_tag("MOTOR_TAG", description=ENGLISH_DESC)

    return _make_controller(
        programs=[italian_program, english_program],
        controller_tags=[it_tag, en_tag],
    )


# ---------------------------------------------------------------------------
# Helper: generate HTML
# ---------------------------------------------------------------------------

def _gen(bilingual: bool, use_online: bool = False) -> str:
    from l5x_documenter.html_generator import HTMLGenerator
    ctrl = _make_bilingual_controller()
    gen = HTMLGenerator(ctrl, bilingual=bilingual, use_online=use_online)
    return gen.generate()


# ---------------------------------------------------------------------------
# Test: bilingual=True — HTML spans
# ---------------------------------------------------------------------------

class TestBilingualHtmlSpans:

    def test_italian_description_produces_i18n_span(self):
        """An Italian free-text description emits <span class="i18n" ...>."""
        output = _gen(bilingual=True)
        assert 'class="i18n"' in output, (
            "Expected i18n span for Italian description, not found in output"
        )

    def test_i18n_span_has_both_lang_attrs(self):
        """The i18n span must carry data-en and data-it attributes."""
        output = _gen(bilingual=True)
        span_re = re.compile(
            r'<span class="i18n"[^>]*data-en="([^"]*)"[^>]*data-it="([^"]*)"[^>]*>'
        )
        spans = span_re.findall(output)
        assert spans, "No <span class=\"i18n\" data-en=... data-it=...> found"
        # At least one span where en != it (actually bilingual)
        assert any(en != it for en, it in spans), (
            "All i18n spans have en==it — no actual bilingual translation found"
        )

    def test_english_description_has_no_i18n_span(self):
        """English-only description must NOT produce an i18n span."""
        output = _gen(bilingual=True)
        # MOTOR_TAG has description "Motor running" (English) — must appear as plain
        # escaped text, not wrapped in an i18n span.
        # We look for the literal string appearing WITHOUT a preceding span-open tag
        # on the same run.  The Italian description translates to lowercase
        # "motor running" (en), which appears INSIDE a span — a different string.
        # The English source "Motor running" (capital M) should appear as a plain
        # table-cell text node: `<td>Motor running</td>`.
        plain_pattern = re.compile(r'<td>Motor running</td>')
        assert plain_pattern.search(output), (
            "Expected 'Motor running' as plain <td> text (no i18n span)"
        )
        # Also confirm it does NOT appear as the visible text of an i18n span
        # (the span's inner text — after '>') on the same line:
        span_pattern = re.compile(r'<span class="i18n"[^>]*>Motor running</span>')
        assert not span_pattern.search(output), (
            "English description 'Motor running' should not be the content of an i18n span"
        )

    def test_italian_identifier_display_has_i18n_id_span(self):
        """An Italian program name produces <span class=\"i18n-id\" ...>."""
        output = _gen(bilingual=True)
        # Nastro1 (Italian) should get bilingual span
        assert 'class="i18n-id"' in output, (
            "Expected i18n-id span for Italian identifier 'Nastro1'"
        )

    def test_italian_identifier_display_shows_english_form(self):
        """The i18n-id span's visible content is the English form (with parens)."""
        output = _gen(bilingual=True)
        # translate_identifier('Nastro1') → {"en": "Nastro1 (Conveyor1)", "it": "Nastro1"}
        # The visible (en) content should appear inside the span
        assert "Nastro1 (Conveyor1)" in output, (
            "English display form 'Nastro1 (Conveyor1)' not found in output"
        )

    def test_raw_identifier_stays_native_in_section_id(self):
        """Section IDs and JS arguments use raw Italian name, not the translated display."""
        output = _gen(bilingual=True)
        # The section id="program-Nastro1" must use raw name
        assert 'id="program-Nastro1"' in output, (
            "Section id should use raw Italian name 'Nastro1', not translated form"
        )

    def test_toggle_control_present_when_bilingual(self):
        """<div class=\"lang-toggle\"...> is injected when bilingual=True."""
        output = _gen(bilingual=True)
        assert 'id="lang-toggle"' in output, (
            "lang-toggle div not found when bilingual=True"
        )
        assert 'class="lang-btn active"' in output and 'data-lang="en"' in output, (
            "EN button with active class not found in lang-toggle"
        )
        assert 'data-lang="it"' in output, (
            "IT button not found in lang-toggle"
        )

    def test_body_data_lang_attribute_when_bilingual(self):
        """<body data-lang="en"> when bilingual=True."""
        output = _gen(bilingual=True)
        assert '<body data-lang="en">' in output, (
            "<body data-lang=\"en\"> not found when bilingual=True"
        )


# ---------------------------------------------------------------------------
# Test: bilingual=True — __LADDER_DATA__ JSON
# ---------------------------------------------------------------------------

class TestBilingualLadderData:

    def test_italian_tag_description_is_object_in_tagdata(self):
        """tagData[].description for an Italian tag is a {en,it} object."""
        output = _gen(bilingual=True)
        data = _extract_ladder_data(output)
        tag_data = data["tagData"]

        nastro_tag = next(
            (t for t in tag_data if t["name"] == "NASTRO_TAG"),
            None,
        )
        assert nastro_tag is not None, "NASTRO_TAG not found in tagData"

        desc = nastro_tag["description"]
        assert isinstance(desc, dict), (
            f"Expected dict for Italian tag description, got {type(desc).__name__}: {desc!r}"
        )
        assert "en" in desc and "it" in desc, (
            f"description object missing 'en'/'it' keys: {desc}"
        )
        assert desc["it"] == ITALIAN_DESC, (
            f"Italian text not preserved: {desc['it']!r}"
        )
        assert desc["en"] != desc["it"], (
            "en and it should differ for Italian text"
        )

    def test_english_tag_description_is_plain_string_in_tagdata(self):
        """tagData[].description for an English tag stays a plain string even when bilingual=True."""
        output = _gen(bilingual=True)
        data = _extract_ladder_data(output)
        tag_data = data["tagData"]

        motor_tag = next(
            (t for t in tag_data if t["name"] == "MOTOR_TAG"),
            None,
        )
        assert motor_tag is not None, "MOTOR_TAG not found in tagData"
        desc = motor_tag["description"]
        assert isinstance(desc, str), (
            f"English tag description should be plain string, got {type(desc).__name__}: {desc!r}"
        )


# ---------------------------------------------------------------------------
# Test: bilingual=False — byte-identical (no spans, no objects)
# ---------------------------------------------------------------------------

class TestNonBilingualIdentical:

    def test_no_i18n_span_when_bilingual_false(self):
        """When bilingual=False, output contains NO class=\"i18n\" spans."""
        output = _gen(bilingual=False)
        assert 'class="i18n"' not in output, (
            "Found i18n span in non-bilingual output — should be absent"
        )

    def test_no_i18n_id_span_when_bilingual_false(self):
        """When bilingual=False, output contains NO class=\"i18n-id\" spans."""
        output = _gen(bilingual=False)
        assert 'class="i18n-id"' not in output, (
            "Found i18n-id span in non-bilingual output — should be absent"
        )

    def test_tagdata_descriptions_plain_strings_when_bilingual_false(self):
        """When bilingual=False, tagData[].description fields are plain strings."""
        output = _gen(bilingual=False)
        data = _extract_ladder_data(output)
        for tag in data["tagData"]:
            desc = tag["description"]
            assert isinstance(desc, str), (
                f"Tag {tag['name']!r} description should be plain str when bilingual=False, "
                f"got {type(desc).__name__}: {desc!r}"
            )

    def test_no_lang_toggle_when_bilingual_false(self):
        """lang-toggle control is absent when bilingual=False."""
        output = _gen(bilingual=False)
        assert 'id="lang-toggle"' not in output, (
            "lang-toggle found in non-bilingual output — should be absent"
        )

    def test_no_body_data_lang_when_bilingual_false(self):
        """<body data-lang=...> is absent when bilingual=False."""
        output = _gen(bilingual=False)
        assert '<body data-lang' not in output, (
            "body element should not carry data-lang when bilingual=False"
        )

    def test_italian_desc_plain_text_non_bilingual(self):
        """Italian description renders as plain (untranslated) escaped text when bilingual=False."""
        output = _gen(bilingual=False)
        # The raw Italian text should be present escaped
        assert html.escape(ITALIAN_DESC) in output or ITALIAN_DESC in output, (
            "Italian description not found in non-bilingual output"
        )
        # The text is used as a key check — it should NOT be translated
        # (bilingual=False = no translation)


# ---------------------------------------------------------------------------
# Test: i18n JS/CSS asset gating (fix-round finding — spec violation)
#
# assets/js/05-i18n.js and assets/i18n.css must be inlined ONLY for
# bilingual docs. A non-bilingual doc's inlined bundle must be byte-for-byte
# identical to the pre-bilingual-feature generator, which never carried any
# language-toggle code or styling.
# ---------------------------------------------------------------------------

class TestI18nAssetGating:

    def test_bilingual_output_contains_picklang_js(self):
        """bilingual=True inlines assets/js/05-i18n.js (pickLang present)."""
        output = _gen(bilingual=True)
        assert 'function pickLang' in output, (
            "pickLang() not found in bilingual output — 05-i18n.js not inlined"
        )

    def test_bilingual_output_contains_lang_toggle_css(self):
        """bilingual=True inlines assets/i18n.css (#lang-toggle rule present)."""
        output = _gen(bilingual=True)
        assert '#lang-toggle' in output, (
            "#lang-toggle CSS rule not found in bilingual output — i18n.css not inlined"
        )

    def test_non_bilingual_output_has_no_i18n_js(self):
        """bilingual=False must not inline any part of 05-i18n.js."""
        output = _gen(bilingual=False)
        for marker in ('pickLang', 'setLang', 'rerenderForLang', 'updateI18nSpans', 'updateLangButtons', 'initI18n'):
            assert marker not in output, (
                f"Found {marker!r} in non-bilingual output — 05-i18n.js must not be inlined "
                "when bilingual=False"
            )

    def test_non_bilingual_output_has_no_lang_toggle_css(self):
        """bilingual=False must not inline i18n.css's language-toggle rules."""
        output = _gen(bilingual=False)
        for marker in ('#lang-toggle', '.lang-toggle', '.lang-btn'):
            assert marker not in output, (
                f"Found {marker!r} in non-bilingual output — i18n.css must not be inlined "
                "when bilingual=False"
            )


# ---------------------------------------------------------------------------
# Test: raw identifier correctness
# ---------------------------------------------------------------------------

class TestRawIdentifierCorrectness:

    def test_showusages_onclick_uses_raw_name(self):
        """showUsages() onclick argument stays the raw tag name, never a span."""
        output = _gen(bilingual=True)
        # The onclick should reference the raw tag name
        assert "showUsages('NASTRO_TAG')" in output, (
            "showUsages() should use raw tag name 'NASTRO_TAG', not a translated span"
        )

    def test_section_id_uses_raw_program_name(self):
        """Section IDs use raw program name (identifier), not bilingual display."""
        output = _gen(bilingual=True)
        assert 'id="program-Nastro1"' in output, (
            "section id should use raw program name"
        )

    def test_section_id_uses_raw_routine_name(self):
        """Routine section ID uses raw routine name (identifier)."""
        output = _gen(bilingual=True)
        # sec_id = f"routine-{prog_id}-{routine.name}"
        assert f'id="routine-Nastro1-{ITALIAN_ROUTINE_NAME}"' in output, (
            f"Routine section id should reference raw name '{ITALIAN_ROUTINE_NAME}'"
        )


# ---------------------------------------------------------------------------
# Test: _t and _id helpers (unit-level)
# ---------------------------------------------------------------------------

class TestEmitterHelpers:

    def _make_gen(self, bilingual: bool):
        from l5x_documenter.html_generator import HTMLGenerator
        ctrl = _make_bilingual_controller()
        return HTMLGenerator(ctrl, bilingual=bilingual, use_online=False)

    def test_t_italian_bilingual_returns_span(self):
        """_t(italian_text) when bilingual=True returns an i18n span."""
        gen = self._make_gen(bilingual=True)
        result = gen._t(ITALIAN_DESC)
        assert 'class="i18n"' in result
        assert 'data-en=' in result
        assert 'data-it=' in result

    def test_t_english_bilingual_returns_plain(self):
        """_t(english_text) when bilingual=True returns plain escaped text (no span)."""
        gen = self._make_gen(bilingual=True)
        result = gen._t(ENGLISH_DESC)
        assert 'class="i18n"' not in result
        assert result == html.escape(ENGLISH_DESC)

    def test_t_non_bilingual_returns_escaped_plain(self):
        """_t(text) when bilingual=False returns html.escape(text)."""
        gen = self._make_gen(bilingual=False)
        assert gen._t(ITALIAN_DESC) == html.escape(ITALIAN_DESC)
        assert gen._t(ENGLISH_DESC) == html.escape(ENGLISH_DESC)

    def test_t_empty_string(self):
        """_t('') returns empty string in both modes."""
        gen_bi = self._make_gen(bilingual=True)
        gen_no = self._make_gen(bilingual=False)
        assert gen_bi._t("") == ""
        assert gen_no._t("") == ""

    def test_id_italian_bilingual_returns_span(self):
        """_id(italian_name) when bilingual=True returns an i18n-id span."""
        gen = self._make_gen(bilingual=True)
        result = gen._id(ITALIAN_PROG_NAME)  # 'Nastro1'
        assert 'class="i18n-id"' in result
        assert 'data-en=' in result
        assert 'data-it=' in result

    def test_id_english_bilingual_returns_plain(self):
        """_id(english_name) when bilingual=True returns plain escaped name."""
        gen = self._make_gen(bilingual=True)
        result = gen._id(ENGLISH_PROG_NAME)
        assert 'class="i18n-id"' not in result
        assert result == html.escape(ENGLISH_PROG_NAME)

    def test_id_non_bilingual_returns_escaped_plain(self):
        """_id(name) when bilingual=False returns html.escape(name)."""
        gen = self._make_gen(bilingual=False)
        assert gen._id(ITALIAN_PROG_NAME) == html.escape(ITALIAN_PROG_NAME)

    def test_tj_italian_bilingual_returns_dict(self):
        """_tj(italian_text) when bilingual=True returns {en, it} dict."""
        gen = self._make_gen(bilingual=True)
        result = gen._tj(ITALIAN_DESC)
        assert isinstance(result, dict)
        assert "en" in result and "it" in result
        assert result["it"] == ITALIAN_DESC

    def test_tj_english_bilingual_returns_plain(self):
        """_tj(english_text) when bilingual=True returns plain string."""
        gen = self._make_gen(bilingual=True)
        result = gen._tj(ENGLISH_DESC)
        assert isinstance(result, str)
        assert result == ENGLISH_DESC

    def test_tj_non_bilingual_returns_plain(self):
        """_tj(text) when bilingual=False returns plain string always."""
        gen = self._make_gen(bilingual=False)
        assert gen._tj(ITALIAN_DESC) == ITALIAN_DESC
        assert gen._tj(ENGLISH_DESC) == ENGLISH_DESC

    def test_tj_empty_string(self):
        """_tj('') returns '' in both modes."""
        gen_bi = self._make_gen(bilingual=True)
        gen_no = self._make_gen(bilingual=False)
        assert gen_bi._tj("") == ""
        assert gen_no._tj("") == ""

    def test_idj_italian_bilingual_returns_dict(self):
        """_idj(italian_name) when bilingual=True returns {en, it} dict."""
        gen = self._make_gen(bilingual=True)
        result = gen._idj(ITALIAN_PROG_NAME)
        assert isinstance(result, dict)
        assert "en" in result and "it" in result
        assert result["it"] == ITALIAN_PROG_NAME

    def test_idj_english_bilingual_returns_plain(self):
        """_idj(english_name) when bilingual=True returns plain string."""
        gen = self._make_gen(bilingual=True)
        result = gen._idj(ENGLISH_PROG_NAME)
        assert isinstance(result, str)
        assert result == ENGLISH_PROG_NAME

    def test_idj_non_bilingual_returns_plain(self):
        """_idj(name) when bilingual=False returns plain string always."""
        gen = self._make_gen(bilingual=False)
        assert gen._idj(ITALIAN_PROG_NAME) == ITALIAN_PROG_NAME


# ---------------------------------------------------------------------------
# Fixtures: fix-round additions — network tree + routineIndex bilingual fields
# ---------------------------------------------------------------------------

ITALIAN_MODULE_NAME = "Zona1"      # Italian: zona -> zone (translates via glossary)
ENGLISH_MODULE_NAME = "IOModule1"  # English (no translation)
ITALIAN_ROUTINE_NAME_2 = "Avvio1"  # Italian: avvio -> start (translates via glossary)


def _make_module(name: str, catalog: str = "1756-EN2T", parent_module: str = "",
                  parent_port: str = ""):
    from l5x_documenter.parser import Module
    return Module(
        name=name,
        catalog_number=catalog,
        vendor="Rockwell",
        slot="",
        parent_module=parent_module,
        parent_port=parent_port,
        ports=[],
    )


def _make_network_controller():
    """Controller with one Italian- and one English-named module wired to the backplane."""
    it_module = _make_module(ITALIAN_MODULE_NAME, parent_port="A")
    en_module = _make_module(ENGLISH_MODULE_NAME, parent_port="B")
    return _make_controller(modules=[it_module, en_module])


def _make_routine_index_controller():
    """Controller with an Italian program/routine pair for routineIndex display fields."""
    routine = _make_routine(name=ITALIAN_ROUTINE_NAME_2, rungs=[_make_rung(0)])
    program = _make_program(name=ITALIAN_PROG_NAME, routines=[routine])
    return _make_controller(programs=[program])


def _gen_for(ctrl, bilingual: bool, use_online: bool = False) -> str:
    from l5x_documenter.html_generator import HTMLGenerator
    gen = HTMLGenerator(ctrl, bilingual=bilingual, use_online=use_online)
    return gen.generate()


# ---------------------------------------------------------------------------
# Test: networkTree bilingual display fields (fix-round finding #1)
# ---------------------------------------------------------------------------

class TestBilingualNetworkTree:

    def test_italian_module_name_is_object_in_networktree_bilingual(self):
        """networkTree node 'name' for an Italian module is a {en,it} object when bilingual=True."""
        ctrl = _make_network_controller()
        output = _gen_for(ctrl, bilingual=True)
        data = _extract_ladder_data(output)
        tree = data["networkTree"]
        assert tree is not None, "networkTree should be present"

        it_node = next(
            (n for n in tree.get("children", []) if n["id"] == ITALIAN_MODULE_NAME),
            None,
        )
        assert it_node is not None, f"{ITALIAN_MODULE_NAME} node not found in networkTree children"

        name = it_node["name"]
        assert isinstance(name, dict), (
            f"Expected {{en,it}} object for Italian module name, got "
            f"{type(name).__name__}: {name!r}"
        )
        assert name["it"] == ITALIAN_MODULE_NAME
        assert name["en"] != name["it"]
        # The node id (used for lookup/DataSet keys) must stay the raw name.
        assert it_node["id"] == ITALIAN_MODULE_NAME

    def test_english_module_name_is_plain_string_bilingual(self):
        """An English module name stays a plain string even when bilingual=True (en == it)."""
        ctrl = _make_network_controller()
        output = _gen_for(ctrl, bilingual=True)
        data = _extract_ladder_data(output)
        tree = data["networkTree"]

        en_node = next(
            (n for n in tree.get("children", []) if n["id"] == ENGLISH_MODULE_NAME),
            None,
        )
        assert en_node is not None, f"{ENGLISH_MODULE_NAME} node not found in networkTree children"
        assert isinstance(en_node["name"], str)

    def test_networktree_plain_strings_when_bilingual_false(self):
        """When bilingual=False, all networkTree display fields are plain strings (unchanged)."""
        ctrl = _make_network_controller()
        output = _gen_for(ctrl, bilingual=False)
        data = _extract_ladder_data(output)
        tree = data["networkTree"]
        assert tree is not None

        assert isinstance(tree["name"], str)
        for node in tree.get("children", []):
            assert isinstance(node["name"], str), (
                f"node name should be plain string when bilingual=False: {node}"
            )
            if "edge_label" in node and node["edge_label"]:
                assert isinstance(node["edge_label"], str), (
                    f"edge_label should be plain string when bilingual=False: {node}"
                )

        assert 'class="i18n"' not in output
        assert 'class="i18n-id"' not in output


# ---------------------------------------------------------------------------
# Test: routineIndex bilingual display fields (fix-round finding #2)
# ---------------------------------------------------------------------------

class TestBilingualRoutineIndex:

    def test_routineindex_display_fields_are_objects_when_italian_bilingual(self):
        """routineIndex entries gain displayRoutine/displayProgram {en,it} objects,
        while the raw program/routine/section/kind lookup keys stay untouched."""
        ctrl = _make_routine_index_controller()
        output = _gen_for(ctrl, bilingual=True)
        data = _extract_ladder_data(output)

        entry = next(
            (e for e in data["routineIndex"] if e["routine"] == ITALIAN_ROUTINE_NAME_2),
            None,
        )
        assert entry is not None, "routineIndex entry not found"

        # Raw lookup keys stay raw.
        assert entry["program"] == ITALIAN_PROG_NAME
        assert entry["routine"] == ITALIAN_ROUTINE_NAME_2
        assert entry["section"] == f"program-{ITALIAN_PROG_NAME}"
        assert entry["kind"] == "program"

        display_routine = entry["displayRoutine"]
        display_program = entry["displayProgram"]
        assert isinstance(display_routine, dict), (
            f"displayRoutine should be an {{en,it}} object, got {display_routine!r}"
        )
        assert isinstance(display_program, dict), (
            f"displayProgram should be an {{en,it}} object, got {display_program!r}"
        )
        assert display_routine["it"] == ITALIAN_ROUTINE_NAME_2
        assert display_routine["en"] != display_routine["it"]
        assert display_program["it"] == ITALIAN_PROG_NAME
        assert display_program["en"] != display_program["it"]

    def test_routineindex_no_display_fields_when_bilingual_false(self):
        """When bilingual=False, routineIndex entries carry NO displayRoutine/
        displayProgram keys at all (not even as plain strings) — the
        non-bilingual __LADDER_DATA__ shape must match the pre-bilingual
        generator exactly, since 10-navigation.js's non-bilingual code path
        reads the raw program/routine fields directly instead."""
        ctrl = _make_routine_index_controller()
        output = _gen_for(ctrl, bilingual=False)
        data = _extract_ladder_data(output)

        entry = next(
            (e for e in data["routineIndex"] if e["routine"] == ITALIAN_ROUTINE_NAME_2),
            None,
        )
        assert entry is not None, "routineIndex entry not found"
        assert "displayRoutine" not in entry, (
            f"displayRoutine key should be absent when bilingual=False, got {entry!r}"
        )
        assert "displayProgram" not in entry, (
            f"displayProgram key should be absent when bilingual=False, got {entry!r}"
        )


# ---------------------------------------------------------------------------
# Fixtures: final-review fix — AOI identifiers get no bilingual treatment
#
# AOIs are the last identifier class (tag/program/routine/AOI) that still
# emitted raw html.escape() everywhere: sidebar nav, the AOI detail section
# header, and its nested routine header. This mirrors the already-correct
# program/routine coverage above.
# ---------------------------------------------------------------------------

ITALIAN_AOI_NAME = "Pompa1"           # Italian: pompa -> pump (glossary)
ENGLISH_AOI_NAME = "ValveCtrl"        # English (no translation)
ITALIAN_AOI_ROUTINE_NAME = "Avvio2"   # Italian: avvio -> start (glossary)


def _make_aoi(name: str, routines: list | None = None, description: str = ""):
    from l5x_documenter.parser import AddOnInstruction
    return AddOnInstruction(
        name=name,
        revision="1.0",
        vendor="Test",
        description=description,
        routines=routines or [],
    )


def _make_aoi_controller():
    """Controller with an Italian-named AOI (with an Italian-named nested
    routine) and an English-named AOI, for AOI-identifier bilingual tests."""
    it_routine = _make_routine(name=ITALIAN_AOI_ROUTINE_NAME, rungs=[_make_rung(0)])
    it_aoi = _make_aoi(ITALIAN_AOI_NAME, routines=[it_routine])
    en_aoi = _make_aoi(ENGLISH_AOI_NAME, routines=[_make_routine(name="Logic", rungs=[_make_rung(0)])])
    return _make_controller(add_on_instructions=[it_aoi, en_aoi])


# ---------------------------------------------------------------------------
# Test: AOI nav / section header / nested routine header bilingual display
# ---------------------------------------------------------------------------

class TestBilingualAoiIdentifiers:

    def test_aoi_nav_italian_name_is_i18n_id_span_bilingual(self):
        """Sidebar AOI nav link label gets an i18n-id span for an Italian AOI name."""
        ctrl = _make_aoi_controller()
        output = _gen_for(ctrl, bilingual=True)
        assert "Pompa1 (Pump1)" in output, (
            "Expected bilingual display form 'Pompa1 (Pump1)' for AOI nav label"
        )
        assert 'class="i18n-id"' in output

    def test_aoi_nav_href_and_onclick_use_raw_name(self):
        """AOI nav href/onclick keep the raw identifier, never the translated span."""
        ctrl = _make_aoi_controller()
        output = _gen_for(ctrl, bilingual=True)
        assert f'href="#aoi-{ITALIAN_AOI_NAME}"' in output
        assert f"showSection('aoi-{ITALIAN_AOI_NAME}')" in output

    def test_aoi_section_header_italian_name_is_i18n_id_span_bilingual(self):
        """AOI detail <section> id stays raw; its <h2> label is bilingual."""
        ctrl = _make_aoi_controller()
        output = _gen_for(ctrl, bilingual=True)
        assert f'<section id="aoi-{ITALIAN_AOI_NAME}" class="section">' in output
        # The h2 for the Italian AOI carries the bilingual display form.
        section_match = re.search(
            rf'<section id="aoi-{ITALIAN_AOI_NAME}" class="section">.*?</section>',
            output, re.DOTALL,
        )
        assert section_match, "AOI section not found"
        assert 'class="i18n-id"' in section_match.group(0)
        assert "Pompa1 (Pump1)" in section_match.group(0)

    def test_aoi_routine_header_italian_name_is_i18n_id_span_bilingual(self):
        """The AOI's nested routine <h4> header is bilingual for an Italian routine name."""
        ctrl = _make_aoi_controller()
        output = _gen_for(ctrl, bilingual=True)
        assert "Avvio2 (Start2)" in output, (
            "Expected bilingual display form 'Avvio2 (Start2)' for AOI routine header"
        )

    def test_aoi_english_name_stays_plain_bilingual(self):
        """An English AOI name never gets wrapped in an i18n-id span."""
        ctrl = _make_aoi_controller()
        output = _gen_for(ctrl, bilingual=True)
        # The plain escaped English AOI name must appear un-wrapped somewhere
        # (nav link and/or section header).
        assert re.search(
            rf'>{ENGLISH_AOI_NAME}<', output,
        ) or re.search(rf'>\s*{ENGLISH_AOI_NAME}\s*<', output), (
            f"Expected plain (non-span) occurrence of {ENGLISH_AOI_NAME!r}"
        )
        section_match = re.search(
            rf'<section id="aoi-{ENGLISH_AOI_NAME}" class="section">.*?</section>',
            output, re.DOTALL,
        )
        assert section_match
        assert 'class="i18n-id"' not in section_match.group(0)

    def test_aoi_nav_section_routine_header_plain_when_bilingual_false(self):
        """When bilingual=False, AOI nav/section/routine-header output is exactly
        html.escape()'d — no i18n-id spans anywhere, and the raw Italian text is
        present untranslated."""
        ctrl = _make_aoi_controller()
        output = _gen_for(ctrl, bilingual=False)
        assert 'class="i18n-id"' not in output
        assert f'<a href="#aoi-{ITALIAN_AOI_NAME}" ' in output
        assert f'</svg> {html.escape(ITALIAN_AOI_NAME)}</a>' in output
        assert f'<h2><svg class="icon icon-lg"><use href="#mdi-wrench"></use></svg> {html.escape(ITALIAN_AOI_NAME)}</h2>' in output
        assert f'<h4>{html.escape(ITALIAN_AOI_ROUTINE_NAME)}</h4>' in output
        assert "Pompa1 (Pump1)" not in output
        assert "Avvio2 (Start2)" not in output
