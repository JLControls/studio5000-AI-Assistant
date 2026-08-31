#!/usr/bin/env python3
"""MCP integration adapter for the l5x_documenter pipeline.

Exposes :class:`L5XDocumenterMCPIntegration` -- one async method per MCP tool,
mirroring ``IgnitionMCPIntegration`` / ``TagMCPIntegration``. This is a thin,
procedural (no LLM) layer over ``l5x_documenter.pipeline``: it validates
inputs, delegates the actual work to the pipeline library (off the event
loop, via ``run_in_executor``, since ``document``/``split``/``run_full`` are
synchronous and can take a while on a large project), and shapes the result
into ``{'success': bool, ...}`` -- output file paths and summary counts only,
never file contents.

These tools are standalone and procedural: they do not chain to, and are not
part of, the comment_graph analysis workflow (``analyze_comment_graph`` /
``generate_program_comments``).

Generated PLC documentation always requires engineering review before use on
a live control system.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


@contextlib.contextmanager
def _stdout_to_stderr():
    """Redirect stdout to stderr for the duration of a pipeline call.

    ``pipeline.document``/``pipeline.split``/``pipeline.run_full`` print
    human-readable progress lines unconditionally (even with verbose=False) --
    harmless for the ``plc-docgen`` CLI, but fatal to the MCP server's
    JSON-RPC framing over stdio, where every stdout line must be exactly one
    JSON-RPC message. The stdio loop (``studio5000_mcp_server.main``)
    processes one request at a time -- it awaits each ``handle_mcp_request``
    fully before reading the next line -- so this process-global swap is safe
    across the ``run_in_executor`` call it wraps here.
    """
    original = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = original


def _split_summary(out_dir: Path) -> Dict[str, Any]:
    """Counts read from a split run's ``_index.json`` / ``_cross_references.json``.

    Never reads the per-routine XML bodies -- just the two small summary
    artifacts ``process_l5x`` already writes.
    """
    summary: Dict[str, Any] = {
        "controller": "",
        "programs": 0,
        "routines": 0,
        "aois": 0,
        "tags_indexed": 0,
    }

    index_path = out_dir / "_index.json"
    if index_path.exists():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            index_data = {}
        programs = index_data.get("programs", [])
        aois = index_data.get("aois", [])
        summary["controller"] = index_data.get("controller", "")
        summary["programs"] = len(programs)
        summary["aois"] = len(aois)
        summary["routines"] = (
            sum(len(p.get("routines", [])) for p in programs)
            + sum(len(a.get("routines", [])) for a in aois)
        )

    xref_path = out_dir / "_cross_references.json"
    if xref_path.exists():
        try:
            xref_data = json.loads(xref_path.read_text(encoding="utf-8"))
            summary["tags_indexed"] = xref_data.get("tag_count", 0)
        except (OSError, json.JSONDecodeError):
            pass

    return summary


class L5XDocumenterMCPIntegration:
    """Offline engine backing the two l5x_documenter MCP tools (procedural, no LLM)."""

    def __init__(self):
        self.initialized = True

    # -- tool #1 -------------------------------------------------------
    async def generate_plc_documentation(
        self,
        input_path: str,
        output_dir: Optional[str] = None,
        translate: Optional[bool] = None,
        online_translate: bool = False,
        inline_assets: bool = False,
        full_pipeline: bool = False,
    ) -> Dict[str, Any]:
        """Generate HTML PLC documentation for an L5X file/directory, or run
        the full ACD -> L5X -> HTML pipeline for an .ACD source.

        ``translate`` is a tri-state bilingual (Italian/English) override:
        ``None`` (default) auto-detects per file from its source path
        (Colussi/Vemac integrators); ``True``/``False`` forces it on/off.

        ``full_pipeline=True`` requires an ``.ACD`` input; it runs
        ``l5x_documenter.pipeline.run_full`` (convert -> split -> document),
        writing every artifact next to the source ACD. That stage does not
        accept ``output_dir``/``translate``/``online_translate``/
        ``inline_assets`` overrides -- any of those passed alongside
        ``full_pipeline=True`` are reported back under ``ignored_params``
        rather than silently applied.

        Without ``full_pipeline``, this calls ``pipeline.document`` directly
        against an existing L5X file or a directory tree.

        Returns output file path(s) and summary counts -- never file
        contents.
        """
        from l5x_documenter import pipeline

        source = Path(input_path)
        if not source.exists():
            return {"success": False, "error": f"Input path not found: {source}"}

        is_acd = source.is_file() and source.suffix.lower() == ".acd"
        loop = asyncio.get_event_loop()

        if full_pipeline:
            if not is_acd:
                return {
                    "success": False,
                    "error": (
                        f"full_pipeline=True requires an .ACD input file (got: {source})"
                    ),
                }

            ignored = []
            if output_dir:
                ignored.append("output_dir")
            if translate is not None:
                ignored.append("translate")
            if online_translate:
                ignored.append("online_translate")
            if inline_assets:
                ignored.append("inline_assets")

            with _stdout_to_stderr():
                result = await loop.run_in_executor(None, pipeline.run_full, source)

            response: Dict[str, Any] = {
                "success": bool(result.get("success")),
                "mode": "full_pipeline",
                "input_path": str(source),
            }
            if ignored:
                response["ignored_params"] = ignored
                response["note"] = (
                    "full_pipeline writes every artifact next to the source ACD "
                    f"using pipeline defaults; not applied to this run: {', '.join(ignored)}."
                )

            if not result.get("success"):
                response["error"] = result.get("error", "pipeline failed")
                return response

            convert_result = result.get("convert") or {}
            response["l5x_path"] = (
                convert_result.get("l5x_path") or convert_result.get("output_path")
            )
            if "size_kb" in convert_result:
                response["l5x_size_kb"] = convert_result.get("size_kb")
            if "inventory" in convert_result:
                response["l5x_inventory"] = convert_result.get("inventory")

            split_result = result.get("split")
            if split_result:
                split_out_dir = split_result.get("out_dir")
                response["split_out_dir"] = split_out_dir
                if split_out_dir:
                    response["split_summary"] = _split_summary(Path(split_out_dir))

            document_result = result.get("document")
            if document_result:
                generated = [str(p) for p in document_result.get("generated", [])]
                response["generated"] = generated
                response["documents_generated"] = len(generated)
                index_path = document_result.get("index")
                response["index"] = str(index_path) if index_path else None

            return response

        # Non-full-pipeline: document() over an existing L5X file or directory.
        with _stdout_to_stderr():
            result = await loop.run_in_executor(
                None,
                functools.partial(
                    pipeline.document,
                    source,
                    output=output_dir,
                    translate_override=translate,
                    use_online=online_translate,
                    inline_assets=inline_assets,
                ),
            )

        response = {
            "success": bool(result.get("success")),
            "mode": "document",
            "input_path": str(source),
        }
        if not result.get("success"):
            response["error"] = result.get("error", "documentation generation failed")
            return response

        generated = [str(p) for p in result.get("generated", [])]
        response["generated"] = generated
        response["documents_generated"] = len(generated)
        index_path = result.get("index")
        response["index"] = str(index_path) if index_path else None
        return response

    # -- tool #2 -------------------------------------------------------
    async def split_l5x(self, l5x_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Split a monolithic L5X into per-routine XML files + index/xref/tag CSV.

        Returns the ``l5x_individual/`` output directory plus counts
        (programs/routines/AOIs/tags indexed) read from its generated
        ``_index.json`` / ``_cross_references.json`` -- never file contents.
        """
        from l5x_documenter import pipeline

        source = Path(l5x_path)
        loop = asyncio.get_event_loop()
        with _stdout_to_stderr():
            result = await loop.run_in_executor(
                None, functools.partial(pipeline.split, source, out_dir=output_dir)
            )

        response: Dict[str, Any] = {
            "success": bool(result.get("success")),
            "input_path": str(source),
        }
        if not result.get("success"):
            response["error"] = result.get("error", "split failed")
            return response

        out_dir = result.get("out_dir")
        response["out_dir"] = out_dir
        if out_dir:
            response.update(_split_summary(Path(out_dir)))
        return response
