"""Ignition SCADA tag-integration exporter.

Generalized, project-agnostic tooling that turns any Studio 5000 L5X/ACD project
into Ignition v8.1+ tag exports: analog-scaling detection (signal-flow aware),
OPC item-path auditing, historian recommendations, folder-tree proposals, and
name sanitization.

The engine (:class:`ignition_mcp_integration.IgnitionMCPIntegration`) is pure and
offline -- no vector DB, no sentence-transformers -- so the MCP ``--test`` smoke
path stays fast.

NOTE: generated PLC/SCADA output always requires engineering review and Studio
5000 / Ignition validation before use on a live control system.
"""

from .l5x_tags import IgnitionTagDB, load_tag_db
from .ignition_tag_builder import IgnitionTagBuilder, flatten_tags, sanitize_name

__all__ = [
    "IgnitionTagDB",
    "load_tag_db",
    "IgnitionTagBuilder",
    "flatten_tags",
    "sanitize_name",
]
