"""Kemco HA105 regression for the issue #28 fact accessors.

Reproduces the exact facts an analyst previously pulled by hand-parsing the L5X:
a configured scalar value, and the ``PSet2_LL1`` invocation's argument→parameter
binding that proved the discharge-pump enables were real.

The Kemco export is proprietary and untracked (see the project memory), so these
tests skip cleanly when the fixture is not present locally.
"""
import os

import pytest

from l5x_analyzer.l5x_fact_accessor import decode_aoi_call, describe_aoi, get_tag_value

KEMCO = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "acd", "KemcoWaterHeater", "Kemco_HA105.L5X",
)

pytestmark = pytest.mark.skipif(
    not os.path.exists(KEMCO),
    reason="Kemco HA105 L5X fixture not available locally (proprietary, untracked).",
)


def test_kemco_configured_scalar_values():
    assert get_tag_value(KEMCO, "Htr1_Set_Htr1_L_Sleep")["value"] == 12
    assert get_tag_value(KEMCO, "Htr1_Cmd_Pumped")["value"] == 1


def test_kemco_pset2_ll1_argument_binds_to_input_en_p1():
    result = decode_aoi_call(
        KEMCO, "Disch_P", 0, program_name="Htr1", aoi_name="PSet2_LL1"
    )
    assert result["success"] is True
    call = result["calls"][0]
    assert call["backing_tag"] == "Htr1_Disch_P"
    assert call["mismatch"] is False
    bindings = {b["param_name"]: b for b in call["bindings"]}
    assert bindings["Input_En_P1"]["operand"] == "Htr1_Cmd_Disch_P1_En"
    assert bindings["Input_En_P1"]["usage"] == "Input"


def test_kemco_describe_pset2_ll1_has_full_parameter_list():
    result = describe_aoi(KEMCO, "PSet2_LL1")
    assert result["success"] is True
    # 37 parameters preserved in the native export (see #9 validation notes).
    assert len(result["parameters"]) == 37
    assert result["parameters"][0]["name"] == "EnableIn"
