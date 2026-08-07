"""Tests for agent-authored tag_overrides in generate_ignition_tags (tool #2).

Overrides let the agent supply human-friendly node names, clean descriptions and a
process-folder hierarchy for the curated tag set -- restoring the human-readable output
that a raw mechanical export cannot produce. Scaling / historian / verification behaviour
is unchanged.
"""

import asyncio
import json

import pytest

from ignition_exporter.ignition_mcp_integration import IgnitionMCPIntegration


def _run(coro):
    return asyncio.run(coro)


def _generate(synthetic_l5x, tmp_path, overrides, **kwargs):
    out = tmp_path / "ignitionTags_enhanced.json"
    engine = IgnitionMCPIntegration()
    result = _run(engine.generate_ignition_tags(
        synthetic_l5x, "DeviceA", str(out), tag_overrides=overrides, **kwargs))
    return result, out


def _atomic_tags(out_path):
    """(full_folder_path, tag_dict) for every AtomicTag, path components '/'-joined."""
    tree = json.loads(out_path.read_text(encoding="utf-8"))

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("tagType") == "AtomicTag":
                yield path, node
            elif node.get("tagType") == "Folder":
                child_path = f"{path}/{node.get('name')}" if path else node.get("name")
                for child in node.get("tags", []):
                    yield from walk(child, child_path)

    return list(walk(tree, ""))


def test_override_name_doc_tooltip_verbatim(synthetic_l5x, tmp_path):
    result, out = _generate(synthetic_l5x, tmp_path, [{
        "plc_tag": "Com_Sump_Lvl",
        "name": "Sump Level",
        "documentation": "Wet Well Sump Level",
        "tooltip": "Operator sump level readout",
    }])
    assert result["success"] is True
    assert result["selection_mode"] == "tag_overrides"
    assert result["overrides_applied"] == 1

    tags = [t for _, t in _atomic_tags(out)]
    assert len(tags) == 1
    tag = tags[0]
    assert tag["name"] == "Sump Level"
    assert tag["documentation"] == "Wet Well Sump Level"
    assert tag["tooltip"] == "Operator sump level readout"
    # The generic template must be suppressed when the agent authored the doc.
    assert "Value Set By" not in tag["documentation"]
    assert "Controls:" not in tag["documentation"]


def test_override_nested_folder_hierarchy(synthetic_l5x, tmp_path):
    _, out = _generate(synthetic_l5x, tmp_path, [{
        "plc_tag": "Com_Sump_Lvl",
        "name": "Sump Level",
        "folder": "Plant/Sump Station/Level",
    }])
    paths = [p for p, _ in _atomic_tags(out)]
    assert paths == ["DeviceA/Plant/Sump Station/Level"]


def test_override_precedence_over_selection(synthetic_l5x, tmp_path):
    # Even with selection='all', overrides define exactly the exported set.
    result, out = _generate(synthetic_l5x, tmp_path, [
        {"plc_tag": "Com_Sump_Lvl", "name": "Sump Level"},
        {"plc_tag": "DIn_Pump_Aux", "name": "Pump Aux Contact"},
    ], selection="all")
    assert result["selection_mode"] == "tag_overrides"
    names = sorted(t["name"] for _, t in _atomic_tags(out))
    assert names == ["Pump Aux Contact", "Sump Level"]
    assert result["tags_written"] == 2


def test_override_synthetic_tag_is_rejected(synthetic_l5x, tmp_path):
    out = tmp_path / "ignitionTags_enhanced.json"
    engine = IgnitionMCPIntegration()
    with pytest.raises(ValueError, match="[Ss]ynthetic"):
        _run(engine.generate_ignition_tags(
            synthetic_l5x, "DeviceA", str(out),
            tag_overrides=[{"plc_tag": "Does_Not_Exist", "name": "Ghost"}]))
    assert not out.exists()


def test_override_preserves_correct_scaling(synthetic_l5x, tmp_path):
    _, out = _generate(synthetic_l5x, tmp_path, [{
        "plc_tag": "AIn_Turbidity_Raw",
        "name": "Turbidity",
        "documentation": "Raw turbidity analog input",
        "folder": "Filtration/Turbidity",
    }])
    tags = [t for _, t in _atomic_tags(out)]
    assert len(tags) == 1
    tag = tags[0]
    assert tag["name"] == "Turbidity"
    # Overrides touch naming only -- the corrected scaling model still applies.
    assert tag["scaleMode"] == "Linear"
    assert tag["rawLow"] == 0.0 and tag["rawHigh"] == 4095.0
    assert tag["scaledLow"] == 0.0 and tag["scaledHigh"] == 100.0
    assert "engLow" in tag and "engHigh" in tag


def test_override_no_value_deadband_keys(synthetic_l5x, tmp_path):
    _, out = _generate(synthetic_l5x, tmp_path, [{
        "plc_tag": "Com_Sump_Lvl", "name": "Sump Level", "folder": "Plant/Sump",
    }])
    raw = out.read_text(encoding="utf-8")
    for forbidden in ("historicalDeadband", "historicalDeadbandMode", "deadbandStyle", '"deadband"'):
        assert forbidden not in raw
