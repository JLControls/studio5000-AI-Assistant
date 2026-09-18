from plc_instruction_semantics import (
    COMMON_INSTRUCTIONS,
    OperandRole,
    get_instruction_operand_role,
    get_operand_indices,
    is_destructive,
    is_known_instruction,
)
from tag_analyzer.comment_pipeline import PLCCommentPipeline


def test_operand_role_values_are_json_safe():
    assert OperandRole.READ_SOURCE.value == "READ_SOURCE"
    assert OperandRole.WRITE_DESTINATION.value == "WRITE_DESTINATION"
    assert OperandRole.READ_WRITE_CONTROL.value == "READ_WRITE_CONTROL"
    assert OperandRole.AOI_INPUT.value == "AOI_INPUT"
    assert OperandRole.AOI_OUTPUT.value == "AOI_OUTPUT"
    assert OperandRole.AOI_INOUT.value == "AOI_INOUT"
    assert OperandRole.UNKNOWN.value == "UNKNOWN"


def test_shared_table_classifies_core_operand_roles():
    assert get_instruction_operand_role("XIC", 0, 1) is OperandRole.READ_SOURCE
    assert get_instruction_operand_role("OTE", 0, 1) is OperandRole.WRITE_DESTINATION
    assert get_instruction_operand_role("ONS", 0, 1) is OperandRole.READ_WRITE_CONTROL
    assert get_instruction_operand_role("MOV", 0, 2) is OperandRole.READ_SOURCE
    assert get_instruction_operand_role("MOV", 1, 2) is OperandRole.WRITE_DESTINATION
    assert get_instruction_operand_role("ADD", 2, 3) is OperandRole.WRITE_DESTINATION
    assert get_instruction_operand_role("TON", 0, 3) is OperandRole.READ_WRITE_CONTROL
    assert get_instruction_operand_role("RES", 0, 1) is OperandRole.WRITE_DESTINATION
    assert get_instruction_operand_role("SCP", 5, 6) is OperandRole.WRITE_DESTINATION


def test_shared_table_resolves_last_operand_and_destructive_state():
    assert get_operand_indices("ADD", 3) == ((0, 1), (2,), ())
    assert get_operand_indices("COP", 3) == ((0,), (1,), ())
    assert get_operand_indices("ONS", 1) == ((), (), (0,))
    assert is_destructive("OTE") is True
    assert is_destructive("TON") is True
    assert is_destructive("ONS") is True
    assert is_destructive("XIC") is False


def test_unknown_instruction_has_no_direction_or_destructive_effect():
    assert get_instruction_operand_role("CUSTOM_AOI", 0, 2) is OperandRole.UNKNOWN
    assert get_operand_indices("CUSTOM_AOI", 2) == ((), (), ())
    assert is_destructive("CUSTOM_AOI") is False
    assert is_known_instruction("CUSTOM_AOI") is False
    assert "MOV" in COMMON_INSTRUCTIONS


def test_comment_pipeline_uses_shared_destructive_roles():
    result = PLCCommentPipeline.parse_rung_structure(
        "XIC(Start) TON(Timer1,1000,0);"
    )
    assert result["outputs"] == [("TON", "Timer1,1000,0")]
