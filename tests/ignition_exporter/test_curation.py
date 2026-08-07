"""Tests for tag curation: the discovery inventory and curated/explicit selection.

The generator no longer dumps every tag. It presents a categorized inventory
(``list_ignition_tag_candidates``) for agent-driven curation, defaults to a curated
"key process metrics" selection, and accepts an explicit ``target_tags`` list.
"""

import asyncio
import json

from ignition_exporter.ignition_mcp_integration import IgnitionMCPIntegration
from ignition_exporter.tag_curation import classify_category, list_ignition_tag_candidates


def _run(coro):
    return asyncio.run(coro)


def _opc_refs(out_path):
    tree = json.loads(out_path.read_text(encoding="utf-8"))

    def walk(node):
        if isinstance(node, dict):
            if node.get("tagType") == "AtomicTag":
                yield node.get("opcItemPath", "")
            for c in node.get("tags", []):
                yield from walk(c)
        elif isinstance(node, list):
            for i in node:
                yield from walk(i)

    return list(walk(tree))


def test_inventory_categorizes_and_recommends(synthetic_l5x):
    inv = list_ignition_tag_candidates(synthetic_l5x)
    assert inv["success"] is True
    by_name = {c["name"]: c for c in inv["candidates"]}
    # operator-facing -> recommended
    assert by_name["Com_Sump_Lvl"]["category"] == "analog_pv"
    assert by_name["Com_Sump_Lvl"]["recommended"] is True
    assert by_name["Com_Set_Sump_Lvl_Sc"]["category"] == "setpoint"
    assert by_name["DIn_Pump_Aux"]["category"] == "status"
    # noise -> not recommended
    assert by_name["Com_Comms_Drive_Status"]["category"] == "comms"
    assert by_name["Com_Comms_Drive_Status"]["recommended"] is False
    assert by_name["Cnfg_Scan_Buf"]["category"] == "config"
    assert by_name["Cnfg_Scan_Buf"]["recommended"] is False
    # scaling-AOI instances are internal
    assert by_name["AIn_Tank_Level"]["category"] == "internal"


def test_classify_category_units():
    from ignition_exporter.l5x_tags import TagEntry
    assert classify_category(TagEntry("Com_Comms_X", "Controller", "", "INT")) == "comms"
    assert classify_category(TagEntry("Cnfg_Buf", "Controller", "", "INT")) == "config"
    assert classify_category(TagEntry("X_Alm_HighTemp", "Controller", "", "BOOL")) == "alarm"
    assert classify_category(TagEntry("Com_Set_Level_Sc", "Controller", "", "REAL")) == "setpoint"
    assert classify_category(TagEntry("Com_AliasDIn_P1_Aux", "Controller", "", "BOOL")) == "field_io"


def test_curated_default_excludes_noise_includes_metrics(synthetic_l5x, tmp_path):
    out = tmp_path / "curated.json"
    engine = IgnitionMCPIntegration()
    result = _run(engine.generate_ignition_tags(synthetic_l5x, "DeviceA", str(out)))
    assert result["selection_mode"] == "key_process_metrics"
    raw = out.read_text(encoding="utf-8")
    # key metrics present
    assert "Com_Sump_Lvl" in raw
    # noise excluded
    assert "Com_Comms_Drive_Status" not in raw
    assert "Cnfg_Scan_Buf" not in raw


def test_all_selection_exports_more_than_curated(synthetic_l5x, tmp_path):
    engine = IgnitionMCPIntegration()
    curated = tmp_path / "c.json"
    everything = tmp_path / "a.json"
    r_c = _run(engine.generate_ignition_tags(synthetic_l5x, "D", str(curated)))
    r_a = _run(engine.generate_ignition_tags(synthetic_l5x, "D", str(everything), selection="all"))
    assert r_a["tags_written"] > r_c["tags_written"]
    assert "Com_Comms_Drive_Status" in everything.read_text(encoding="utf-8")


def test_unwritten_scratch_status_pruned_from_default(synthetic_l5x, tmp_path):
    # BUG-007: a BOOL that matches a status token but is never written and is not a
    # physical-field device is dead scratch -> pruned by the Balanced discriminator,
    # while a real physical-field status point (DIn_Pump_Aux) stays recommended.
    inv = list_ignition_tag_candidates(synthetic_l5x)
    by_name = {c["name"]: c for c in inv["candidates"]}
    assert by_name["Seq_Step_Run"]["category"] == "status"
    assert by_name["Seq_Step_Run"]["recommended"] is False
    assert "Seq_Step_Run" not in inv["recommended_tags"]
    assert by_name["DIn_Pump_Aux"]["recommended"] is True

    out = tmp_path / "curated.json"
    engine = IgnitionMCPIntegration()
    _run(engine.generate_ignition_tags(synthetic_l5x, "DeviceA", str(out)))
    assert "Seq_Step_Run" not in out.read_text(encoding="utf-8")


def test_expandable_struct_members_surface_in_inventory(synthetic_l5x):
    # BUG-008 discovery side: composite struct roots are expanded to recommended
    # atomic members in the candidate inventory.
    inv = list_ignition_tag_candidates(synthetic_l5x)
    names = {c["name"] for c in inv["candidates"]}
    assert {"Com_CW.Flow", "Com_CW.Tot", "Com_HWT1.Temp"} <= names
    assert "Com_CW.Flow" in inv["recommended_tags"]


def test_target_tags_curates_explicitly(synthetic_l5x, tmp_path):
    out = tmp_path / "explicit.json"
    engine = IgnitionMCPIntegration()
    result = _run(engine.generate_ignition_tags(
        synthetic_l5x, "DeviceA", str(out), target_tags=["Com_Sump_Lvl", "DIn_Pump_Aux"]))
    assert result["selection_mode"] == "target_tags"
    refs = _opc_refs(out)
    bases = {r.split("]")[-1].split(".")[0] for r in refs}
    assert bases == {"Com_Sump_Lvl", "DIn_Pump_Aux"}
