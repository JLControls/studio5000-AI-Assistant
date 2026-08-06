"""Integration tests for generate_ignition_tags (tool #2) and sanitize (tool #6)."""

import asyncio
import json

import pytest

from ignition_exporter.ignition_mcp_integration import IgnitionMCPIntegration
from ignition_exporter.ignition_tag_builder import flatten_tags


def _run(coro):
    return asyncio.run(coro)


def _generate(synthetic_l5x, tmp_path, **kwargs):
    out = tmp_path / "ignitionTags_enhanced.json"
    engine = IgnitionMCPIntegration()
    # These structural/scaling tests exercise the full tag set; curation is covered
    # separately in test_curation.py.
    kwargs.setdefault("selection", "all")
    result = _run(engine.generate_ignition_tags(
        synthetic_l5x, "DeviceA", str(out), **kwargs))
    return result, out


def _load_tags(out_path):
    tree = json.loads(out_path.read_text(encoding="utf-8"))
    flat, _ = flatten_tags(tree)
    return tree, flat


def test_generate_writes_file_and_reports(synthetic_l5x, tmp_path):
    result, out = _generate(synthetic_l5x, tmp_path)
    assert result["success"] is True
    assert out.exists()
    assert result["tags_written"] > 0


def test_generate_never_emits_value_deadband_keys(synthetic_l5x, tmp_path):
    _, out = _generate(synthetic_l5x, tmp_path)
    raw = out.read_text(encoding="utf-8")
    for forbidden in ("historicalDeadband", "historicalDeadbandMode", "deadbandStyle", '"deadband"'):
        assert forbidden not in raw


def test_generate_scaled_tag_has_scaled_keys_distinct_from_eng(synthetic_l5x, tmp_path):
    _, out = _generate(synthetic_l5x, tmp_path)
    _, flat = _load_tags(out)
    # the raw-hardware point (AIn_Turbidity_Raw) must be scaled by Ignition
    scaled = [t for opc, t in _tags_with_opc(out) if "AIn_Turbidity_Raw" in opc]
    assert scaled, "expected the raw turbidity point in the export"
    tag = scaled[0]
    assert tag["scaleMode"] == "Linear"
    assert tag["rawLow"] == 0.0 and tag["rawHigh"] == 4095.0
    assert tag["scaledLow"] == 0.0 and tag["scaledHigh"] == 100.0
    assert "engLow" in tag and "engHigh" in tag  # distinct keys


def _tags_with_opc(out_path):
    """Yield (opcItemPath, tag_dict) for every atomic tag in the export."""
    tree = json.loads(out_path.read_text(encoding="utf-8"))

    def walk(node):
        if isinstance(node, dict):
            if node.get("tagType") == "AtomicTag":
                yield node.get("opcItemPath", ""), node
            for child in node.get("tags", []):
                yield from walk(child)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    return list(walk(tree))


def test_generate_excludes_external_access_none(synthetic_l5x, tmp_path):
    result, out = _generate(synthetic_l5x, tmp_path)
    raw = out.read_text(encoding="utf-8")
    assert "Secret_Internal" not in raw
    assert "Turbidity_PV_Internal" not in raw
    assert "Secret_Internal" in result["excluded_external_access_none"] or \
           any("Secret_Internal" in x for x in result["excluded_external_access_none"])


def test_generate_program_scope_prefix(synthetic_l5x, tmp_path):
    _, out = _generate(synthetic_l5x, tmp_path)
    opc_paths = [opc for opc, _ in _tags_with_opc(out)]
    assert any("Program:MainProgram.Prog_Report_Rate" in opc for opc in opc_paths)


def test_generate_udt_member_addressing(synthetic_l5x, tmp_path):
    _, out = _generate(synthetic_l5x, tmp_path)
    opc_paths = [opc for opc, _ in _tags_with_opc(out)]
    assert any("Cycle_Ctr.ACC" in opc for opc in opc_paths)
    assert any("Cycle_Ctr.DN" in opc for opc in opc_paths)
    # never the bare COUNTER struct
    assert not any(opc.endswith("]Cycle_Ctr") for opc in opc_paths)


def test_generate_guardrail_refuses_baseline_filename(synthetic_l5x, tmp_path):
    out = tmp_path / "ignitionTags.json"
    engine = IgnitionMCPIntegration()
    result = _run(engine.generate_ignition_tags(synthetic_l5x, "DeviceA", str(out)))
    assert result["success"] is False
    assert "baseline" in result["error"].lower()
    assert not out.exists()


def test_sanitize_ignition_nodes_string_and_list():
    engine = IgnitionMCPIntegration()
    one = _run(engine.sanitize_ignition_nodes("Level & Volume"))
    assert one["results"][0]["sanitized"] == "Level and Volume"
    assert one["results"][0]["changed"] is True

    many = _run(engine.sanitize_ignition_nodes(["Clean_Name", "Bad/Name"]))
    assert many["count"] == 2
    assert many["results"][0]["changed"] is False
    assert many["results"][1]["sanitized"] == "Bad Name"
