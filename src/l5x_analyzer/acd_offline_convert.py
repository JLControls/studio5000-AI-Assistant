#!/usr/bin/env python3
"""High-fidelity offline ACD to L5X conversion for Studio 5000 v38 files."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import weakref
import xml.dom.minidom
from pathlib import Path
from typing import Any, Dict

from .l5x_semantic_validation import compare_l5x, inventory_l5x


_ACD_SOURCE = Path(os.environ.get("ACD_TOOLS_SOURCE", r"F:\git\work\acd"))
_PATCHED = False


def _load_acd_source() -> None:
    if not _ACD_SOURCE.is_dir():
        raise ImportError(
            f"acd source checkout not found: {_ACD_SOURCE}. "
            "Set ACD_TOOLS_SOURCE to the hutcheb/acd checkout."
        )
    source = str(_ACD_SOURCE)
    if source not in sys.path:
        sys.path.insert(0, source)


def _apply_runtime_compatibility() -> None:
    """Use a disposable extraction directory without replacing serializers."""
    global _PATCHED
    if _PATCHED:
        return

    _load_acd_source()
    import acd.l5x.export_l5x

    original_post_init = acd.l5x.export_l5x.ExportL5x.__post_init__

    def post_init_with_disposable_build(self):
        if self._temp_dir == "build":
            self._temp_dir = tempfile.mkdtemp(prefix="acd_build_")
            self._finalizer = weakref.finalize(
                self, shutil.rmtree, self._temp_dir, ignore_errors=True
            )
        original_post_init(self)

    acd.l5x.export_l5x.ExportL5x.__post_init__ = post_init_with_disposable_build
    _PATCHED = True


def convert_acd_to_l5x(
    input_path: str | Path,
    output_path: str | Path,
    pretty: bool = True,
    reference_path: str | Path | None = None,
) -> Dict[str, Any]:
    """Convert an ACD without the SDK and optionally compare to a Studio export."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.exists():
        return {"success": False, "error": f"Input file not found: {input_path}"}

    try:
        _apply_runtime_compatibility()
        from acd.api import ImportProjectFromFile
    except ImportError as exc:
        return {"success": False, "error": str(exc)}

    try:
        project = ImportProjectFromFile(str(input_path)).import_project()
        xml_content = project.to_xml()
        if pretty:
            try:
                xml_content = xml.dom.minidom.parseString(xml_content).toprettyxml(indent="  ")
            except Exception:
                pass

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(xml_content, encoding="utf-8")
        result: Dict[str, Any] = {
            "success": True,
            "output_path": str(output_path),
            "size_kb": round(output_path.stat().st_size / 1024, 1),
            "acd_source": str(_ACD_SOURCE),
            "inventory": {key: len(value) for key, value in inventory_l5x(output_path).items()},
            "note": (
                "Offline v38 conversion; no Logix Designer SDK was initialized. "
                "Use validation against a matching Studio export to quantify unsupported fields; "
                "do not deploy/import when validation.import_safe is false."
            ),
        }
        if reference_path is not None:
            reference_path = Path(reference_path)
            if not reference_path.exists():
                result["validation"] = {
                    "status": "unavailable",
                    "error": f"Reference L5X not found: {reference_path}",
                }
            else:
                result["validation"] = compare_l5x(output_path, reference_path)
        return result
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
