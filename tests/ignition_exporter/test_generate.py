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


def test_generate_expands_udt_struct_to_atomic_members(synthetic_l5x, tmp_path):
    # BUG-008: complex UDT/AOI struct roots (FData1/TData1) must be pruned; only their
    # atomic scalar members are exported, with correct per-member Ignition data types.
    _, out = _generate(synthetic_l5x, tmp_path)  # selection="all"
    pairs = _tags_with_opc(out)
    opc_paths = [opc for opc, _ in pairs]

    # struct roots never appear as scalar OPC items
    assert not any(opc.endswith("]Com_CW") for opc in opc_paths)
    assert not any(opc.endswith("]Com_HWT1") for opc in opc_paths)

    # atomic members are present
    assert any("Com_CW.Flow" in opc for opc in opc_paths)
    assert any("Com_CW.Tot" in opc for opc in opc_paths)
    assert any("Com_HWT1.Temp" in opc for opc in opc_paths)

    # per-member data types are correct (not all-Float4)
    by_ref = {opc.split("]")[-1]: t for opc, t in pairs}
    assert by_ref["Com_CW.Flow"]["dataType"] == "Float4"
    assert by_ref["Com_CW.Tot_ACC"]["dataType"] == "Int4"
    assert by_ref["Com_HWT1.Temp"]["dataType"] == "Float4"


def test_generate_override_bare_struct_root_expands_to_members(synthetic_l5x, tmp_path):
    # BUG-008 override path: a bare expandable struct root passed in tag_overrides is
    # auto-expanded into its atomic members, inheriting the friendly name/folder.
    out = tmp_path / "override_struct.json"
    engine = IgnitionMCPIntegration()
    result = _run(engine.generate_ignition_tags(
        synthetic_l5x, "DeviceA", str(out),
        tag_overrides=[{"plc_tag": "Com_CW", "name": "CW Flow", "folder": "Cold Water"}]))
    assert result["success"] is True

    pairs = _tags_with_opc(out)
    opc_paths = [opc for opc, _ in pairs]
    assert not any(opc.endswith("]Com_CW") for opc in opc_paths)
    assert any("Com_CW.Flow" in opc for opc in opc_paths)
    assert any("Com_CW.Tot" in opc for opc in opc_paths)
    # friendly name prefix applied to each member, nested under the override folder
    assert any(t["name"].startswith("CW Flow") for _, t in pairs)
    assert "Cold Water" in out.read_text(encoding="utf-8")


def test_verify_rejects_bare_expandable_struct_root(synthetic_l5x):
    # BUG-008 guardrail: verification refuses a bare complex-struct root, closing the
    # gap that previously only caught COUNTER/TIMER.
    from ignition_exporter.l5x_tags import load_tag_db
    from ignition_exporter.ignition_tag_builder import (
        IgnitionTagBuilder,
        verify_tree_against_l5x,
    )
    db = load_tag_db(synthetic_l5x)
    builder = IgnitionTagBuilder("DeviceA", tag_db=db)
    bad = builder.tag("Cold Water", "Com_CW", "Float4")  # bare FData1 struct root
    tree = builder.folder("Root", [bad])
    with pytest.raises(ValueError, match="struct"):
        verify_tree_against_l5x(db, tree)


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
