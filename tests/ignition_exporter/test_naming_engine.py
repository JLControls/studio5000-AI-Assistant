"""Tests for the pure, deterministic Ignition naming engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ignition_exporter.naming_engine import (
    Presentation,
    build_presentation,
    disambiguate_presentations,
    load_naming_profile,
)


def test_build_presentation_expands_phrase_and_routes_folder():
    profile, _ = load_naming_profile()

    result = build_presentation("Com_HWT1_LP_P2_Cmd_Hz", "", profile)

    assert result.plc_tag == "Com_HWT1_LP_P2_Cmd_Hz"
    assert result.name == "Hot Water Tank Low Pressure Pump 2 Command Speed"
    assert result.folder == "Boiler/Hot Water System/Low Pressure/Pump 2"
    assert result.documentation == result.name
    assert result.tooltip == result.name
    assert result.is_test is False
    assert result.unknown_tokens == ()


@pytest.mark.parametrize(
    ("plc_tag", "expected_name", "expected_folder", "is_test"),
    [
        (
            "Program:MainProgram.Com_HWT1_LP_P2_Cmd_Hz",
            "Hot Water Tank Low Pressure Pump 2 Command Speed",
            "Boiler/Hot Water System/Low Pressure/Pump 2",
            False,
        ),
        (
            "Com_HWT1.Temp",
            "Hot Water Tank Temperature",
            "Boiler/Hot Water Tank/Temperature",
            False,
        ),
        (
            "Com_AliasDIn_HWT1_LP_P2_Aux",
            "Hot Water Tank Low Pressure Pump 2 Aux Contact",
            "Boiler/Hot Water System/Low Pressure/Pump 2",
            False,
        ),
        (
            "Com_Alm_HWT1_LP_P2_Suc_Lo.DN",
            "Alarm Hot Water Tank Low Pressure Pump 2 Suction Low",
            "Boiler/Hot Water System/Low Pressure/Pump 2",
            False,
        ),
        (
            "Test_Com_HWT1_Temp",
            "Hot Water Tank Temperature",
            "Boiler/Diagnostics/Test",
            True,
        ),
        (
            "TOT_01.ACC",
            "Flow Totalizer 1 Accumulator",
            "Boiler/Flow Totalizers",
            False,
        ),
    ],
)
def test_build_presentation_handles_scopes_members_aliases_alarms_and_tests(
    plc_tag: str, expected_name: str, expected_folder: str, is_test: bool
):
    profile, _ = load_naming_profile()

    result = build_presentation(plc_tag, "  source comment  ", profile)

    assert result.name == expected_name
    assert result.folder == expected_folder
    assert result.documentation == "source comment"
    assert result.tooltip == expected_name
    assert result.is_test is is_test


def test_build_presentation_records_unknown_tokens_without_dropping_them():
    profile, _ = load_naming_profile()

    result = build_presentation("Com_HWT1_MysterySignal", "", profile)

    assert result.name == "Hot Water Tank MysterySignal"
    assert result.unknown_tokens == ("MysterySignal",)


def test_build_presentation_keeps_curve_point_index_for_air_rate_characterization():
    profile, _ = load_naming_profile()

    result = build_presentation("Com_Air_R_SCP1", "", profile)

    assert result.name == "Air Rate Curve Point 1"
    assert result.unknown_tokens == ()


def test_profile_test_markers_classify_custom_prefix_and_route_to_diagnostics(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps({"test_markers": ["QA"]}), encoding="utf-8")
    profile, _ = load_naming_profile(str(profile_path))

    result = build_presentation("QA_Com_HWT1_Temp", "", profile)

    assert result.name == "Hot Water Tank Temperature"
    assert result.is_test is True
    assert result.folder == "Boiler/Diagnostics/Test"


def test_profile_extension_overrides_one_token(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps({"tokens": {"HWT1": "Process Tank"}}), encoding="utf-8"
    )

    profile, identity = load_naming_profile(str(profile_path))
    result = build_presentation("Com_HWT1_Temp", "", profile)

    assert result.name == "Process Tank Temperature"
    assert identity == str(profile_path.resolve())
    assert profile.tokens["P2"] == "Pump 2"


def test_profile_extension_overrides_phrases_members_explicit_values_and_display_root(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "display_root": "Utilities",
                "phrases": {"Cmd_Hz": "Requested Speed"},
                "member_suffixes": {"Temp": "Process Temperature"},
                "explicit": {
                    "Com_HWT1_LP_P2_Cmd_Hz": {
                        "name": "Pump 2 Speed Request",
                        "folder": "Custom/Controls",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    profile, _ = load_naming_profile(str(profile_path))

    assert build_presentation("Com_HWT1_LP_P2_Cmd_Hz", "", profile).name == "Pump 2 Speed Request"
    assert build_presentation("Com_HWT1_LP_P2_Cmd_Hz", "", profile).folder == "Custom/Controls"
    assert build_presentation("Com_HWT1_LP_P1_Cmd_Hz", "", profile).name == "Hot Water Tank Low Pressure Pump 1 Requested Speed"
    assert build_presentation("Com_HWT1.Temp", "", profile).name == "Hot Water Tank Process Temperature"
    assert build_presentation("TOT_01.ACC", "", profile).folder == "Utilities/Flow Totalizers"


@pytest.mark.parametrize(
    ("content", "field_name"),
    [
        ("{", "JSON"),
        (json.dumps({"tokens": []}), "tokens"),
        (json.dumps({"phrases": {"Cmd_Hz": 5}}), "phrases"),
        (json.dumps({"member_suffixes": {"DN": 5}}), "member_suffixes"),
        (json.dumps({"aliases": "AliasDIn"}), "aliases"),
        (json.dumps({"explicit": {"tag": "name"}}), "explicit"),
    ],
)
def test_profile_loader_rejects_malformed_or_wrongly_typed_content(
    tmp_path, content: str, field_name: str
):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=field_name):
        load_naming_profile(str(profile_path))


def test_profile_loader_rejects_missing_profile_path(tmp_path):
    missing_path = tmp_path / "missing.json"

    with pytest.raises(ValueError, match="profile"):
        load_naming_profile(str(missing_path))


def test_disambiguate_presentations_uses_alias_qualifier_then_stable_suffixes():
    items = [
        Presentation("Com_HWT1_Temp", "Temperature", "Boiler/Hot Water Tank", "", "Temperature", False, ()),
        Presentation("Com_AliasDIn_HWT1_Temp", "Temperature", "Boiler/Hot Water Tank", "", "Temperature", False, ()),
        Presentation("Com_AliasDOut_HWT1_Temp", "Temperature", "Boiler/Hot Water Tank", "", "Temperature", False, ()),
        Presentation("Com_HWT1_Temp_Copy", "Temperature", "Boiler/Hot Water Tank", "", "Temperature", False, ()),
    ]

    result = disambiguate_presentations(items)

    assert [item.name for item in result] == [
        "Temperature",
        "Temperature (Digital Input)",
        "Temperature (Digital Output)",
        "Temperature 2",
    ]
    assert all(item.tooltip == item.name for item in result)
    assert len({(item.folder, item.name) for item in result}) == len(result)


def test_kemco_style_corpus_meets_name_and_folder_regression_thresholds():
    profile, _ = load_naming_profile()
    fixture = Path(__file__).parent / "fixtures" / "kemco_style_corpus.json"
    corpus = json.loads(fixture.read_text(encoding="utf-8"))

    presentations = [
        build_presentation(entry["plc_tag"], entry.get("documentation", ""), profile)
        for entry in corpus
    ]
    exact_names = sum(item.name == entry["name"] for item, entry in zip(presentations, corpus))
    exact_folders = sum(item.folder == entry["folder"] for item, entry in zip(presentations, corpus))

    assert len(corpus) == 143
    assert exact_names / len(corpus) >= 0.94
    assert exact_folders / len(corpus) >= 0.98
