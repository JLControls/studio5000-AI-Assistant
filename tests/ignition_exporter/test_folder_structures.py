"""Tests for candidate folder-structure proposals (tool #5)."""

from ignition_exporter.folder_structures import (
    VALID_MODELS,
    propose_folder_structures,
)


def test_proposes_requested_number_of_options(synthetic_l5x):
    result = propose_folder_structures(synthetic_l5x, max_options=3)
    assert result["success"] is True
    assert len(result["options"]) == 3
    assert [o["model"] for o in result["options"]] == list(VALID_MODELS)


def test_each_option_has_rationale_and_tree(synthetic_l5x):
    result = propose_folder_structures(synthetic_l5x)
    for option in result["options"]:
        assert option["rationale"]
        assert option["folder_count"] >= 1
        assert isinstance(option["folder_tree"], dict) and option["folder_tree"]


def test_max_options_limits_output(synthetic_l5x):
    result = propose_folder_structures(synthetic_l5x, max_options=1)
    assert len(result["options"]) == 1


def test_excludes_external_access_none_tags(synthetic_l5x):
    # Secret_Internal / Turbidity_PV_Internal are ExternalAccess="None" and must
    # not appear in any proposed tree.
    result = propose_folder_structures(synthetic_l5x)
    blob = repr(result)
    assert "Secret_Internal" not in blob
    assert "Turbidity_PV_Internal" not in blob
