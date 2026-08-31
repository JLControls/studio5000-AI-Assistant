"""
l5x_documenter.pipeline - importable orchestration for the ACD -> L5X -> HTML
documentation pipeline.

No argparse here - this module is the library surface that both
``l5x_documenter.cli`` (the ``plc-docgen`` command) and other callers (the
studio5000-ai-assistant MCP server, git hooks) import directly.

Stage map
---------
convert()             ACD -> L5X (delegates to l5x_analyzer.acd_offline_convert)
split()               L5X -> l5x_individual/ (per-routine XML + index/xref)
document()            L5X (file or directory) -> *_Documentation.html [+ index.html]
run_full()            convert -> split -> document, next to the source ACD
regenerate_changed()  git-diff driven: run_full() for every .ACD changed since a ref
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .parser import L5XParser, TagCrossReference, discover_l5x_files
from .html_generator import generate_documentation
from . import split as split_module

# Integrators whose machines carry Italian-language L5X documentation.
# Kept as a single module-level pattern so it's easy to extend with more
# integrator names later.
import re as _re

ITALIAN_PATH_PATTERN = _re.compile(r'colussi|vemac', _re.IGNORECASE)


def is_italian_source(path) -> bool:
    """True if the L5X source path indicates Italian-origin content (Colussi/Vemac integrators)."""
    return bool(ITALIAN_PATH_PATTERN.search(str(path)))


# ---------------------------------------------------------------------------
# Stage 1: convert
# ---------------------------------------------------------------------------

def convert(acd_path, l5x_path=None, reference_path=None) -> dict:
    """
    Convert an .ACD file to .L5X, offline (acd-tools), no Studio 5000 SDK.

    Args:
        acd_path: Path to the source .ACD file.
        l5x_path: Output .L5X path. Defaults to ``acd_path`` with a ``.l5x``
            suffix, next to the source ACD.
        reference_path: Optional Studio-exported L5X to diff the conversion
            against (fidelity comparison).

    Returns:
        The result dict from
        ``l5x_analyzer.acd_offline_convert.convert_acd_to_l5x`` (has at least
        ``success`` and, on failure, ``error``).
    """
    from l5x_analyzer.acd_offline_convert import convert_acd_to_l5x

    acd_path = Path(acd_path)
    if l5x_path is None:
        l5x_path = acd_path.with_suffix('.l5x')
    else:
        l5x_path = Path(l5x_path)

    result = convert_acd_to_l5x(
        acd_path,
        l5x_path,
        reference_path=reference_path,
    )
    result.setdefault('l5x_path', str(l5x_path))
    return result


# ---------------------------------------------------------------------------
# Stage 2: split
# ---------------------------------------------------------------------------

def split(l5x_path, out_dir=None, verbose: bool = False) -> dict:
    """
    Split a monolithic .L5X file into per-routine XML files + index/xref.

    Args:
        l5x_path: Path to the .L5X file.
        out_dir: Output directory for the split artifacts. Defaults to
            ``l5x_individual/`` next to the source L5X (matches the original
            git-hook / drivers behavior).
        verbose: Print progress.

    Returns:
        {"success": bool, "out_dir": str, "error": str (on failure)}
    """
    l5x_path = Path(l5x_path)
    if not l5x_path.exists():
        return {"success": False, "error": f"L5X file not found: {l5x_path}"}

    try:
        resolved_out_dir = split_module.process_l5x(
            l5x_path, out_dir=Path(out_dir) if out_dir else None, verbose=verbose,
        )
        return {"success": True, "out_dir": str(resolved_out_dir)}
    except Exception as exc:  # noqa: BLE001 - surfaced to caller
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Stage 3: document
# ---------------------------------------------------------------------------

def _process_single_file(
    input_path: Path,
    output_dir: Path,
    translate_override: Optional[bool] = None,
    verbose: bool = False,
    navigation_links: Optional[dict] = None,
    inline_assets: bool = False,
    use_online: bool = False,
) -> Optional[Path]:
    """Process a single L5X file and generate documentation.

    translate_override: Tri-state bilingual override. None (default) =
        auto-detect from input_path via is_italian_source(); True/False
        forces bilingual on/off regardless of the path.
    """
    bilingual = (translate_override if translate_override is not None
                 else is_italian_source(input_path))

    if verbose:
        print(f"Processing: {input_path}")
        print(f"  Bilingual (IT/EN): {bilingual}")

    try:
        parser = L5XParser(input_path)
        controller = parser.parse()

        if verbose:
            print(f"  Controller: {controller.name}")
            print(f"  Processor: {controller.processor_type}")
            print(f"  Programs: {len(controller.programs)}")
            print(f"  Tags: {len(controller.controller_tags)}")

        xref = TagCrossReference(controller)
        xref.build_cross_reference()

        if verbose:
            total_usages = sum(len(t.usages) for t in xref.get_all_tags())
            print(f"  Tag usages indexed: {total_usages}")

        output_path = output_dir / f"{controller.name}_Documentation.html"

        generate_documentation(
            controller,
            output_path,
            translate=bilingual,
            navigation_links=navigation_links,
            inline_assets=inline_assets,
            bilingual=bilingual,
            use_online=use_online,
        )

        if verbose:
            print(f"  Generated: {output_path}")

        return output_path

    except Exception as e:  # noqa: BLE001 - reported to caller, non-fatal per file
        print(f"Error processing {input_path}: {e}", file=sys.stderr)
        if verbose:
            import traceback
            traceback.print_exc()
        return None


def _process_directory(
    input_dir: Path,
    output_dir: Optional[Path] = None,
    translate_override: Optional[bool] = None,
    verbose: bool = False,
    inline_assets: bool = False,
    use_online: bool = False,
) -> list[Path]:
    """Process all L5X files in a directory tree.

    translate_override is resolved PER FILE against that file's own source
    path (a workspace can mix Italian Colussi/Vemac machines with English
    ones in a single run).
    """
    generated = []
    l5x_files = list(discover_l5x_files(input_dir))

    print(f"Found {len(l5x_files)} L5X files")

    nav_links_map = {}
    for l5x_file in l5x_files:
        try:
            parser = L5XParser(l5x_file)
            controller = parser.parse()
            output_filename = f"{controller.name}_Documentation.html"
            if output_dir:
                output_path = output_dir / output_filename
            else:
                output_path = l5x_file.parent / output_filename

            parts = []
            for parent in l5x_file.parent.relative_to(input_dir).parts:
                if parent not in ('plc', 'hmi'):
                    parts.append(parent)

            if parts:
                display_name = ' '.join(parts)
                if len(parts) > 1:
                    clean_parts = []
                    for p in parts:
                        match = _re.match(r'([A-Z][a-z]*)(\d+)', p)
                        if match:
                            word, num = match.groups()
                            clean_parts.append(f"{word} {num}")
                        else:
                            clean_parts.append(p)
                    display_name = ' '.join(clean_parts[-2:])
                else:
                    display_name = parts[0]
            else:
                display_name = controller.name

            nav_links_map[display_name] = (output_path, l5x_file.parent)
        except Exception:
            pass

    for i, l5x_file in enumerate(l5x_files, 1):
        print(f"\n[{i}/{len(l5x_files)}] {l5x_file.name}")

        file_output_dir = output_dir if output_dir else l5x_file.parent

        file_nav_links = {}
        for display_name, (target_path, source_dir) in nav_links_map.items():
            from os.path import relpath
            try:
                rel = relpath(str(target_path), str(file_output_dir))
                file_nav_links[display_name] = rel.replace('\\', '/')
            except ValueError:
                file_nav_links[display_name] = str(target_path).replace('\\', '/')

        bilingual = (translate_override if translate_override is not None
                     else is_italian_source(l5x_file))

        result = _process_single_file(
            l5x_file,
            file_output_dir,
            bilingual,
            verbose,
            navigation_links=file_nav_links,
            inline_assets=inline_assets,
            use_online=use_online,
        )
        if result:
            generated.append(result)

    return generated


def _generate_index(
    output_dir: Path,
    generated_files: list[Path],
    workspace_root: Optional[Path] = None,
) -> Path:
    """Generate an index HTML file listing all generated documentation."""
    if workspace_root:
        index_dir = workspace_root
        index_path = workspace_root / "index.html"
    else:
        index_dir = output_dir
        index_path = output_dir / "index.html"

    file_links = []
    for f in sorted(generated_files):
        try:
            rel_path = os.path.relpath(f, index_dir)
            rel_path = rel_path.replace('\\', '/')
            name = f.stem.replace('_Documentation', '')
            file_links.append(
                f'<li><a href="{rel_path}">{name}</a></li>'
            )
        except (ValueError, TypeError):
            pass

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>L5X Documentation Index</title>
    <style>
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{
            color: #1976D2;
            border-bottom: 3px solid #1976D2;
            padding-bottom: 10px;
        }}
        ul {{
            list-style: none;
            padding: 0;
        }}
        li {{
            margin: 10px 0;
        }}
        a {{
            display: block;
            padding: 15px 20px;
            background: white;
            border-radius: 8px;
            text-decoration: none;
            color: #1976D2;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        a:hover {{
            transform: translateX(5px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }}
        .stats {{
            background: #1976D2;
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 30px;
        }}
    </style>
</head>
<body>
    <h1><svg style="width: 1.3em; height: 1.3em; vertical-align: middle; margin-right: 0.3em;"><use href="#mdi-clipboard-outline"></use></svg> L5X Documentation</h1>
    <svg xmlns="http://www.w3.org/2000/svg" style="display:none">
      <symbol id="mdi-clipboard-outline" viewBox="0 0 24 24"><path fill="currentColor" d="M19,3H14.82C14.4,1.84 13.3,1 12,1C10.7,1 9.6,1.84 9.18,3H5A2,2 0 0,0 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5A2,2 0 0,0 19,3M12,3A1,1 0 0,1 13,4A1,1 0 0,1 12,5A1,1 0 0,1 11,4A1,1 0 0,1 12,3M19,19H5V5H7V7H17V5H19V19Z"/></symbol>
    </svg>
    <div class="stats">
        <strong>{len(generated_files)}</strong> projects documented
    </div>
    <ul>
        {"\n        ".join(file_links)}
    </ul>
</body>
</html>'''

    index_path.write_text(html, encoding='utf-8')
    return index_path


def document(
    input_path,
    output=None,
    translate_override: Optional[bool] = None,
    use_online: bool = False,
    no_index: bool = False,
    inline_assets: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Generate HTML documentation for a single L5X file or a directory tree.

    Bilingual (Italian+English) output is auto-detected PER FILE from each
    L5X's source path: any path containing "colussi" or "vemac"
    (case-insensitive) is documented bilingually. translate_override is a
    tri-state: None (default) = auto-detect; True/False forces bilingual
    on/off for every file processed in this call.

    Args:
        input_path: A single .l5x file or a directory to search recursively.
        output: Output directory. Defaults to next to each source file.
        translate_override: Tri-state bilingual override (see above).
        use_online: Enable the online (deep-translator) MT fallback.
        no_index: Skip generating index.html for a directory run.
        inline_assets: Embed JS/CSS assets directly into each HTML file.
        verbose: Print verbose progress.

    Returns:
        {"success": bool, "generated": [Path, ...], "index": Path | None,
         "error": str (on failure)}
    """
    input_path = Path(input_path)
    output_dir = Path(output) if output else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_file():
        if input_path.suffix.lower() != '.l5x':
            return {"success": False, "error": f"{input_path} is not an L5X file"}

        result = _process_single_file(
            input_path,
            output_dir if output_dir else input_path.parent,
            translate_override,
            verbose,
            inline_assets=inline_assets,
            use_online=use_online,
        )
        if result:
            return {"success": True, "generated": [result], "index": None}
        return {"success": False, "error": f"Failed to generate documentation for {input_path}"}

    if input_path.is_dir():
        generated = _process_directory(
            input_path,
            output_dir,
            translate_override,
            verbose,
            inline_assets=inline_assets,
            use_online=use_online,
        )

        if not generated:
            return {"success": False, "error": "No L5X files found or all processing failed"}

        index_path = None
        if not no_index:
            workspace_root = input_path
            index_path = _generate_index(output_dir, generated, workspace_root)

        return {"success": True, "generated": generated, "index": index_path}

    return {"success": False, "error": f"{input_path} does not exist"}


# ---------------------------------------------------------------------------
# run_full: convert -> split -> document, next to the source ACD
# ---------------------------------------------------------------------------

def run_full(
    acd_path,
    verbose: bool = False,
    skip_split: bool = False,
    skip_doc: bool = False,
) -> dict:
    """
    Run the full ACD -> L5X -> HTML pipeline for one .ACD file, writing all
    artifacts next to the source ACD: ``<name>.l5x``, ``l5x_individual/``,
    and ``<Controller>_Documentation.html`` - the same artifact set the git
    post-merge hook expects.

    Args:
        acd_path: Path to the source .ACD file.
        verbose: Print verbose progress for each stage.
        skip_split: Skip stage 2 (split).
        skip_doc: Skip stage 3 (document).

    Returns:
        {"success": bool, "acd_path": str, "convert": {...},
         "split": {...} | None, "document": {...} | None,
         "error": str (present on failure)}
    """
    acd_path = Path(acd_path)
    summary: dict = {"success": False, "acd_path": str(acd_path)}

    convert_result = convert(acd_path)
    summary["convert"] = convert_result
    if not convert_result.get("success"):
        summary["error"] = convert_result.get("error", "conversion failed")
        return summary

    l5x_path = Path(convert_result.get("l5x_path") or acd_path.with_suffix('.l5x'))

    split_result = None
    if not skip_split:
        split_result = split(l5x_path, verbose=verbose)
        summary["split"] = split_result
        if not split_result.get("success"):
            summary["error"] = split_result.get("error", "split failed")
            return summary
    else:
        summary["split"] = None

    doc_result = None
    if not skip_doc:
        doc_result = document(l5x_path, output=None, verbose=verbose)
        summary["document"] = doc_result
        if not doc_result.get("success"):
            summary["error"] = doc_result.get("error", "documentation failed")
            return summary
    else:
        summary["document"] = None

    summary["success"] = True
    return summary


# ---------------------------------------------------------------------------
# regenerate_changed: git-diff driven regeneration
# ---------------------------------------------------------------------------

def regenerate_changed(since_ref: str, repo_root, verbose: bool = False) -> dict:
    """
    Re-run the full pipeline only for .ACD files changed (added/modified)
    between ``since_ref`` and HEAD in ``repo_root``.

    Ports the logic of ``regenerate_changed.ps1``:
    ``git diff --name-only --diff-filter=AM <since_ref> HEAD -- *.ACD *.acd``,
    then run_full() for each changed, still-present ACD.

    Returns:
        {"since_ref": str, "changed": [rel_path, ...], "skipped": [rel_path, ...],
         "results": {rel_path: run_full() summary dict, ...}, "success": bool}
    """
    repo_root = Path(repo_root)

    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", since_ref, "HEAD",
         "--", "*.ACD", "*.acd"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        return {
            "since_ref": since_ref,
            "success": False,
            "error": proc.stderr.strip() or f"git diff exited {proc.returncode}",
            "changed": [],
            "skipped": [],
            "results": {},
        }

    changed = sorted({line.strip() for line in proc.stdout.splitlines() if line.strip()})

    summary: dict = {
        "since_ref": since_ref,
        "changed": changed,
        "skipped": [],
        "results": {},
        "success": True,
    }

    if not changed:
        if verbose:
            print(f"No changed .ACD files since {since_ref} - nothing to regenerate.")
        return summary

    if verbose:
        print(f"Regenerating docs for {len(changed)} changed ACD file(s)...")

    for rel in changed:
        acd_path = repo_root / rel
        if not acd_path.exists():
            summary["skipped"].append(rel)
            if verbose:
                print(f"  (skipped, file no longer present: {rel})")
            continue

        if verbose:
            print(f"  -> {rel}")

        result = run_full(acd_path, verbose=verbose)
        summary["results"][rel] = result
        if not result.get("success"):
            summary["success"] = False

    return summary
