"""Tests for the signal-flow-aware analog scaling detector.

Exercises, generically (no project-specific names or ranges):
  (i)   analog-input block  -> expose .Output, eng=[ScaledMin,ScaledMax], no scaling
  (ii)  analog-output block -> expose .Input feed, eng=[InputMin,InputMax], no scaling
  (iii) raw point, no addressable engineering tag -> Ignition scales raw->scaled
  (iv)  all-zero members -> ranges resolved from wired SCP constants, not zeros
"""

from ignition_exporter.analog_scaling import extract_analog_scaling


def _by_name(points, name):
    for p in points:
        if p["tag_name"] == name:
            return p
    raise AssertionError(f"point {name!r} not found in {[p['tag_name'] for p in points]}")


def test_extract_reports_success_and_points(synthetic_l5x):
    result = extract_analog_scaling(synthetic_l5x)
    assert result["success"] is True
    assert result["scaled_points_count"] == len(result["scaled_points"])
    assert result["scaled_points_count"] >= 4


def test_case_i_analog_input_exposes_output_engineering(synthetic_l5x):
    points = extract_analog_scaling(synthetic_l5x)["scaled_points"]
    p = _by_name(points, "AIn_Tank_Level")
    assert p["direction"] == "input"
    assert p["is_engineering_units"] is True
    assert p["requires_ignition_scaling"] is False
    # engineering range is the scaled side; raw side (0-10000, non-standard) discarded
    assert p["eng_low"] == 0.0 and p["eng_high"] == 192.0
    assert p["recommended_opc_tag"] == "AIn_Tank_Level.Output"
    # proves the non-standard raw range was read from members, not assumed
    assert "raw_low" not in p or p.get("raw_low") is None


def test_case_ii_analog_output_exposes_input_command(synthetic_l5x):
    points = extract_analog_scaling(synthetic_l5x)["scaled_points"]
    p = _by_name(points, "AOut_Pump_Speed")
    assert p["direction"] == "output"
    assert p["is_engineering_units"] is True
    assert p["requires_ignition_scaling"] is False
    # engineering range is the input (command) side; counts side (0-32767) discarded
    assert p["eng_low"] == 0.0 and p["eng_high"] == 60.0
    assert p["recommended_opc_tag"] == "Cmd_Pump_Hz"


def test_case_iii_raw_hardware_fallback_scales_in_ignition(synthetic_l5x):
    points = extract_analog_scaling(synthetic_l5x)["scaled_points"]
    p = _by_name(points, "AIn_Turbidity_Raw")
    assert p["requires_ignition_scaling"] is True
    assert p["is_engineering_units"] is False
    assert p["recommended_opc_tag"] == "AIn_Turbidity_Raw"
    assert p["raw_low"] == 0.0 and p["raw_high"] == 4095.0
    assert p["scaled_low"] == 0.0 and p["scaled_high"] == 100.0
    # eng_* is a distinct concept from the raw->scaled conversion endpoints
    assert p["scaled_high"] != p["raw_high"]
    assert p["eng_low"] is None and p["eng_high"] is None


def test_case_iv_all_zero_members_resolve_from_wired_constants(synthetic_l5x):
    points = extract_analog_scaling(synthetic_l5x)["scaled_points"]
    p = _by_name(points, "Sc_HdrPres")
    # ranges come from the wired SCP (0,27648,0,150), NOT the all-zero members
    assert p["direction"] == "input"
    assert p["eng_low"] == 0.0 and p["eng_high"] == 150.0
    assert p["requires_ignition_scaling"] is False
    assert "wired SCP constants" in p["scaling_source"]


def test_all_zero_members_without_fallback_flagged_none_found(synthetic_l5x):
    # An all-zero scaling block with no wired constants must be distrusted, not
    # emitted as a [0, 0] range (correction #3: never silently disable).
    points = extract_analog_scaling(synthetic_l5x)["scaled_points"]
    p = _by_name(points, "Sc_Orphan")
    assert p["scaling_source"] == "none_found"
    assert p["eng_low"] is None and p["eng_high"] is None
    assert "warning" in p
    # crucially, it must NOT claim a bogus zero engineering range
    assert p.get("eng_high") != 0.0


def test_transmitter_point_exposes_engineering_pv_from_scale_setpoint(synthetic_l5x):
    # A process transmitter with no SCP block: engineering range comes from a
    # companion _Sc scale setpoint's value, and the recognizable engineering PV is
    # exposed (not a raw or block .Output tag).
    points = extract_analog_scaling(synthetic_l5x)["scaled_points"]
    p = _by_name(points, "Sump_Lvl")
    assert p["direction"] == "input"
    assert p["is_engineering_units"] is True
    assert p["requires_ignition_scaling"] is False
    assert p["recommended_opc_tag"] == "Com_Sump_Lvl"  # the engineering PV, not the raw alias
    assert p["eng_low"] == 0.0 and p["eng_high"] == 120.0  # from Com_Set_Sump_Lvl_Sc = 120.0
    assert "Com_Set_Sump_Lvl_Sc" in p["scaling_source"]


def test_target_tags_filter(synthetic_l5x):
    points = extract_analog_scaling(synthetic_l5x, target_tags=["AIn_Tank_Level"])["scaled_points"]
    assert [p["tag_name"] for p in points] == ["AIn_Tank_Level"]
