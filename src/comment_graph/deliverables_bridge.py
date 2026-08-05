"""Render converged facts into Studio 5000 deliverables and extended memory.

Reuses ``PLCCommentPipeline`` (``src/tag_analyzer/comment_pipeline.py``) verbatim
for the CSV/HTML emission (``generate_deliverables`` :254) and incremental memory
(``manage_incremental_memory`` :1084); this bridge only validates decisions and
layers graph-provenance fields on top of the memory record so stale reuse can be
detected by ``source_artifact_hash`` **and** ``graph_digest``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class DecisionValidationError(ValueError):
    """Raised when a decision lacks a source description, confidence, or status."""


_REQUIRED_FIELDS = ("PROPOSED_DESCRIPTION", "CONFIDENCE", "STATUS")


class DeliverablesBridge:
    """Validates decisions and produces deliverables + extended memory records."""

    def __init__(self, pipeline: Optional[Any] = None) -> None:
        # Injected for tests; lazily constructed in render() when omitted.
        self._pipeline = pipeline

    # -- validation -------------------------------------------------------
    def validate_decisions(self, decisions: List[Dict[str, Any]]) -> None:
        for i, decision in enumerate(decisions):
            for field in _REQUIRED_FIELDS:
                if not decision.get(field):
                    raise DecisionValidationError(
                        f"decision[{i}] ({decision.get('NAME', '?')}) missing {field}"
                    )

    # -- memory -----------------------------------------------------------
    def build_memory_record(
        self,
        base_record: Dict[str, Any],
        provenance: Dict[str, Any],
        convergence_status: str,
        last_converged_pass: int,
        decisions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Layer graph-analysis provenance onto a memory record, additively."""
        record = dict(base_record)
        record["source_artifact_hash"] = provenance.get("source_artifact_hash")
        record["graph_digest"] = provenance.get("graph_digest")
        record["analysis_config"] = provenance.get("analysis_config")
        record["convergence_status"] = convergence_status
        record["last_converged_pass"] = last_converged_pass
        record["decision_dependencies"] = {
            d.get("NAME"): d.get("DEPENDENCY_IDS", [])
            for d in decisions
            if d.get("NAME")
        }
        return record

    def can_reuse(self, prior: Dict[str, Any], current_hash: str, current_digest: str) -> bool:
        """Reuse persisted state only if both the bytes and the graph are unchanged."""
        return (
            prior.get("source_artifact_hash") == current_hash
            and prior.get("graph_digest") == current_digest
        )

    # -- rendering --------------------------------------------------------
    async def render(self, result, request) -> Dict[str, Any]:
        """Generate CSV/HTML and update memory from an AnalysisResult.

        Returns a dict of artifact paths and the memory outcome. Only the final,
        converged decisions are rendered.
        """
        decisions = result.decisions
        self.validate_decisions(decisions)

        pipeline = self._pipeline or self._default_pipeline()
        output = {"decisions": len(decisions)}

        if request.generate_deliverables or request.output_dir:
            # Derive the project name from the artifact stem (no extension); the
            # pipeline also falls back to this when project_name is None.
            base = request.file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            project_name = base.rsplit(".", 1)[0] if "." in base else base
            deliverables = pipeline.generate_deliverables(
                decisions,
                output_dir=request.output_dir,
                project_name=project_name,
                file_path=request.file_path,
                edit_acd=getattr(request, "edit_acd", False),
                target_acd=getattr(request, "target_acd", None),
            )
            output["deliverables"] = deliverables

        if request.memory_file_path:
            memory = pipeline.manage_incremental_memory(
                request.file_path, request.memory_file_path, decisions
            )
            base = memory.get("memory", memory) if isinstance(memory, dict) else {}
            output["memory"] = self.build_memory_record(
                base,
                provenance=result.provenance,
                convergence_status=result.convergence_status.value,
                last_converged_pass=result.last_converged_pass,
                decisions=decisions,
            )

        return output

    def _default_pipeline(self):
        from tag_analyzer.comment_pipeline import PLCCommentPipeline

        return PLCCommentPipeline()
