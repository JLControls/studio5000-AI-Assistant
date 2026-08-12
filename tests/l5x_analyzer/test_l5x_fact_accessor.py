"""Tests for deterministic L5X fact accessors (issue #28).

Three structural, vector-free accessors over an exported L5X:

- ``get_tag_value`` surfaces configured values already present in the decorated
  ``<Data>`` tree (scalars, UDT members, arrays), respecting radix and scope.
- ``describe_aoi`` returns an AOI's parameters in invocation (document) order
  with usage / data type / required / visible.
- ``decode_aoi_call`` maps a rung's AOI-call operands onto those parameters,
  treating operand 0 as the backing instance and binding the rest positionally
  to the required (callable) parameters.
"""
import os

import pytest

from l5x_analyzer.l5x_fact_accessor import (
    decode_aoi_call,
    describe_aoi,
    get_tag_value,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "fact_accessor.L5X")


# --------------------------------------------------------------------------- #
# get_tag_value
# --------------------------------------------------------------------------- #
def test_scalar_controller_tag_value_and_radix():
    result = get_tag_value(FIXTURE, "Ctl_Count")
    assert result["success"] is True
    assert result["scope"] == "controller"
    assert result["program"] is None
    assert result["data_type"] == "DINT"
    assert result["radix"] == "Decimal"
    assert result["value"] == 42


def test_scalar_real_value_is_float():
    result = get_tag_value(FIXTURE, "Trip_Points", member="[1]", program_name="Heater1")
    assert result["success"] is True
    assert result["value"] == 20.0
    assert result["data_type"] == "REAL"
    assert result["radix"] == "Float"


def test_bool_program_tag_value():
    result = get_tag_value(FIXTURE, "Pumped", program_name="Heater1")
    assert result["success"] is True
    assert result["scope"] == "program"
    assert result["program"] == "Heater1"
    assert result["value"] == 1


def test_nested_udt_member_value():
    result = get_tag_value(FIXTURE, "Ctl_Scale", member="Min")
    assert result["success"] is True
    assert result["value"] == 4.0
    assert result["data_type"] == "REAL"


def test_structure_without_member_returns_tree():
    result = get_tag_value(FIXTURE, "Ctl_Scale")
    assert result["success"] is True
    # A structured tree, not a flattened string.
    assert result["value"] == {"Min": 4.0, "Max": 20.0}
    assert result["data_type"] == "ScaleCfg"


def test_array_without_member_returns_list():
    result = get_tag_value(FIXTURE, "Trip_Points", program_name="Heater1")
    assert result["success"] is True
    assert result["value"] == [10.0, 20.0, 30.0]


def test_alias_tag_returns_target_without_inventing_value():
    result = get_tag_value(FIXTURE, "Ctl_Alias_Temp")
    assert result["success"] is True
    assert result["is_alias"] is True
    assert result["alias_for"] == "Local:1:I.Ch03.Data"
    assert result["value"] is None


def test_tag_without_decorated_data_is_unsupported_not_zero():
    result = get_tag_value(FIXTURE, "NoData_Tag", program_name="Heater1")
    assert result["success"] is False
    # Must not silently default to zero; report the missing decorated format.
    assert "value" not in result or result.get("value") is None
    assert "decorated" in result["error"].lower() or "format" in result["error"].lower()


def test_ambiguous_scope_without_program_is_error():
    # Shared_Name exists at controller scope AND in Heater1.
    result = get_tag_value(FIXTURE, "Shared_Name")
    assert result["success"] is False
    assert "ambiguous" in result["error"].lower()


def test_ambiguous_scope_resolved_by_program():
    result = get_tag_value(FIXTURE, "Shared_Name", program_name="Heater1")
    assert result["success"] is True
    assert result["value"] == 99


def test_missing_tag_is_error():
    result = get_tag_value(FIXTURE, "Does_Not_Exist")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


# --------------------------------------------------------------------------- #
# describe_aoi
# --------------------------------------------------------------------------- #
def test_describe_aoi_lists_parameters_in_document_order():
    result = describe_aoi(FIXTURE, "PScale")
    assert result["success"] is True
    names = [p["name"] for p in result["parameters"]]
    assert names == [
        "EnableIn", "EnableOut", "In", "En_P1", "Setpoint", "Out",
        "Opt_Trim", "Gains",
    ]


def test_describe_aoi_parameter_metadata():
    result = describe_aoi(FIXTURE, "PScale")
    params = {p["name"]: p for p in result["parameters"]}
    assert params["In"]["usage"] == "Input"
    assert params["In"]["data_type"] == "REAL"
    assert params["In"]["required"] is True
    assert params["In"]["visible"] is True
    assert params["Setpoint"]["usage"] == "InOut"
    assert params["Out"]["usage"] == "Output"
    assert params["Opt_Trim"]["required"] is False
    assert params["Gains"]["dimensions"] == 4


def test_describe_aoi_unknown_is_error():
    result = describe_aoi(FIXTURE, "NoSuchAOI")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


# --------------------------------------------------------------------------- #
# decode_aoi_call
# --------------------------------------------------------------------------- #
def test_decode_binds_operands_to_required_params():
    result = decode_aoi_call(FIXTURE, "Logic", 0, program_name="Heater1")
    assert result["success"] is True
    assert len(result["calls"]) == 1
    call = result["calls"][0]
    assert call["aoi"] == "PScale"
    assert call["backing_tag"] == "Scaler1"
    bindings = {b["param_name"]: b for b in call["bindings"]}
    assert bindings["In"]["operand"] == "Raw_In"
    assert bindings["In"]["usage"] == "Input"
    assert bindings["Setpoint"]["operand"] == "Sp_Tag"
    assert bindings["Setpoint"]["usage"] == "InOut"
    assert bindings["Out"]["operand"] == "Result_Out"
    assert bindings["Out"]["usage"] == "Output"


def test_decode_marks_na_placeholder():
    result = decode_aoi_call(FIXTURE, "Logic", 0, program_name="Heater1")
    call = result["calls"][0]
    en_p1 = next(b for b in call["bindings"] if b["param_name"] == "En_P1")
    assert en_p1["operand"] == "NA"
    assert en_p1["placeholder"] is True


def test_decode_operand_count_matches_required_params():
    result = decode_aoi_call(FIXTURE, "Logic", 0, program_name="Heater1")
    call = result["calls"][0]
    # In, En_P1, Setpoint, Out are the four Required (callable) params.
    assert call["mismatch"] is False
    assert len(call["bindings"]) == 4


def test_decode_multiple_calls_on_one_rung():
    result = decode_aoi_call(FIXTURE, "Logic", 1, program_name="Heater1")
    assert result["success"] is True
    assert len(result["calls"]) == 2
    assert result["calls"][0]["backing_tag"] == "Scaler2"
    assert result["calls"][1]["backing_tag"] == "Scaler3"


def test_decode_operand_count_mismatch_is_flagged():
    result = decode_aoi_call(FIXTURE, "Logic", 2, program_name="Heater1")
    call = result["calls"][0]
    # Only two operands supplied for four required params.
    assert call["mismatch"] is True


def test_decode_rung_without_aoi_call_returns_empty():
    result = decode_aoi_call(FIXTURE, "Logic", 3, program_name="Heater1")
    assert result["success"] is True
    assert result["calls"] == []


def test_decode_ambiguous_routine_without_program_is_error():
    # "Logic" exists in both Heater1 and Heater2.
    result = decode_aoi_call(FIXTURE, "Logic", 0)
    assert result["success"] is False
    assert "ambiguous" in result["error"].lower()


def test_decode_filter_by_aoi_name():
    result = decode_aoi_call(
        FIXTURE, "Logic", 1, program_name="Heater1", aoi_name="PScale"
    )
    assert result["success"] is True
    assert all(c["aoi"] == "PScale" for c in result["calls"])
