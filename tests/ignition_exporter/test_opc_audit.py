"""Tests for the case-sensitive OPC item-path audit (tool #3)."""

import json

from ignition_exporter.opc_audit import audit_opc_item_paths


def _write_export(tmp_path, device, plc_refs):
    """Write a minimal Ignition JSON export referencing the given PLC refs."""
    tags = [
        {
            "name": ref.replace(".", " "),
            "tagType": "AtomicTag",
            "valueSource": "opc",
            "opcItemPath": f"ns=1;s=[{device}]{ref}",
        }
        for ref in plc_refs
    ]
    tree = {"name": device, "tagType": "Folder", "tags": tags}
    path = tmp_path / "export.json"
    path.write_text(json.dumps(tree), encoding="utf-8")
    return str(path)


def test_audit_detects_case_mismatch_missing_and_none(tmp_path, synthetic_l5x):
    export = _write_export(tmp_path, "DevA", [
        "Cmd_Pump_Hz",          # exact match -> ok
        "cmd_pump_hz",          # case mismatch (base differs only in case)
        "Nonexistent_Tag",      # missing
        "Secret_Internal",      # exists but ExternalAccess="None"
    ])
    result = audit_opc_item_paths(export, synthetic_l5x)

    assert result["audit_status"] == "FAILED"  # a missing tag forces FAILED
    assert result["total_tags_checked"] == 4

    mismatches = {m["referenced_plc_tag"]: m for m in result["case_mismatches"]}
    assert "cmd_pump_hz" in mismatches
    assert mismatches["cmd_pump_hz"]["actual_plc_tag"] == "Cmd_Pump_Hz"

    missing = {m["referenced_plc_tag"] for m in result["missing_tags"]}
    assert "Nonexistent_Tag" in missing

    none_refs = {m["plc_tag"] for m in result["external_access_none"]}
    assert "Secret_Internal" in none_refs


def test_audit_passes_clean_export(tmp_path, synthetic_l5x):
    export = _write_export(tmp_path, "DevA", ["Cmd_Pump_Hz", "DIn_Pump_Aux"])
    result = audit_opc_item_paths(export, synthetic_l5x)
    assert result["audit_status"] == "PASSED"
    assert not result["missing_tags"]
    assert not result["case_mismatches"]
