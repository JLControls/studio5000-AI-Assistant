"""Configuration, request, and result value types for the analysis lifecycle.

Kept dependency-light so it can be imported by both the scheduler and the MCP
orchestrator. Convergence bounds default conservatively (see the plan's
convergence algorithm).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class ConvergenceStatus(Enum):
    CONVERGED = "converged"    # queue empty, no semantic change pending
    BOUNDED = "bounded"        # hit a pass limit with work still pending
    PARTIAL = "partial"        # converged but worker errors / unresolved remain
    FAILED = "failed"          # build/conversion error


@dataclass(frozen=True)
class AnalysisConfig:
    max_passes: int = 8
    max_component_passes: int = 4
    max_workers: int = 4
    enable_instruction_doc: bool = False
    enable_vector_retrieval: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AnalysisConfig":
        if not data:
            return cls()
        allowed = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**allowed)


@dataclass
class AnalysisRequest:
    file_path: str
    reference_path: Optional[str] = None
    generate_deliverables: bool = False
    output_dir: Optional[str] = None
    memory_file_path: Optional[str] = None
    user_seeds: List[Dict[str, Any]] = field(default_factory=list)
    config: AnalysisConfig = field(default_factory=AnalysisConfig)
    edit_acd: bool = False
    target_acd: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisRequest":
        return cls(
            file_path=data["file_path"],
            reference_path=data.get("reference_path"),
            generate_deliverables=bool(data.get("generate_deliverables", False)),
            output_dir=data.get("output_dir"),
            memory_file_path=data.get("memory_file_path"),
            user_seeds=list(data.get("user_seeds", [])),
            config=AnalysisConfig.from_dict(data.get("config")),
            edit_acd=bool(data.get("edit_acd", False)),
            target_acd=data.get("target_acd"),
        )


@dataclass
class AnalysisResult:
    convergence_status: ConvergenceStatus
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    contradictions: List[Dict[str, Any]] = field(default_factory=list)
    assistance_requests: List[Dict[str, Any]] = field(default_factory=list)
    pass_history: List[Dict[str, Any]] = field(default_factory=list)
    last_converged_pass: int = 0
    deliverables: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["convergence_status"] = self.convergence_status.value
        return data
