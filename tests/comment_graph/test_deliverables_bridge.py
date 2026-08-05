"""Unit tests for deliverables_bridge validation + memory extension (Ckpt 6)."""

import pytest

from comment_graph.deliverables_bridge import (
    DeliverablesBridge,
    DecisionValidationError,
)


def _decision(**overrides):
    base = {
        "TYPE": "Tag",
        "SCOPE": "Operand",
        "NAME": "N101[18]",
        "PROPOSED_DESCRIPTION": "calibrated temperature",
        "CONFIDENCE": "HIGH",
        "STATUS": "observed",
        "DEPENDENCY_IDS": ["op:N18[1]"],
    }
    base.update(overrides)
    return base


class TestValidation:
    def test_valid_decision_passes(self):
        DeliverablesBridge().validate_decisions([_decision()])  # no raise

    def test_missing_description_rejected(self):
        with pytest.raises(DecisionValidationError):
            DeliverablesBridge().validate_decisions([_decision(PROPOSED_DESCRIPTION="")])

    def test_missing_confidence_rejected(self):
        d = _decision()
        del d["CONFIDENCE"]
        with pytest.raises(DecisionValidationError):
            DeliverablesBridge().validate_decisions([d])

    def test_missing_status_rejected(self):
        d = _decision()
        del d["STATUS"]
        with pytest.raises(DecisionValidationError):
            DeliverablesBridge().validate_decisions([d])


class TestMemoryExtension:
    def test_additive_fields_added(self):
        provenance = {
            "source_artifact_hash": "abc",
            "graph_digest": "def",
            "analysis_config": {"max_passes": 8},
        }
        record = DeliverablesBridge().build_memory_record(
            {"project": "P", "routines": {}, "tags": {}},
            provenance=provenance,
            convergence_status="converged",
            last_converged_pass=3,
            decisions=[_decision()],
        )
        # Original fields preserved
        assert record["project"] == "P"
        # Additive graph metadata present
        assert record["source_artifact_hash"] == "abc"
        assert record["graph_digest"] == "def"
        assert record["analysis_config"] == {"max_passes": 8}
        assert record["convergence_status"] == "converged"
        assert record["last_converged_pass"] == 3
        # Per-decision dependency IDs captured
        assert record["decision_dependencies"]["N101[18]"] == ["op:N18[1]"]


class TestReuseGuard:
    def test_reuse_refused_when_artifact_hash_differs(self):
        bridge = DeliverablesBridge()
        prior = {"source_artifact_hash": "old", "graph_digest": "g"}
        assert not bridge.can_reuse(prior, current_hash="new", current_digest="g")

    def test_reuse_refused_when_graph_digest_differs(self):
        bridge = DeliverablesBridge()
        prior = {"source_artifact_hash": "h", "graph_digest": "old"}
        assert not bridge.can_reuse(prior, current_hash="h", current_digest="new")

    def test_reuse_allowed_when_both_match(self):
        bridge = DeliverablesBridge()
        prior = {"source_artifact_hash": "h", "graph_digest": "g"}
        assert bridge.can_reuse(prior, current_hash="h", current_digest="g")
