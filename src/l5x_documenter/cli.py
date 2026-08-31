"""
l5x_documenter.cli - the ``plc-docgen`` command-line interface.

Thin click wrappers over ``l5x_documenter.pipeline``. Each subcommand exits
non-zero on failure so it composes cleanly in git hooks / CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import pipeline


@click.group()
@click.version_option(package_name="plc-docgen")
def main():
    """plc-docgen: offline ACD -> L5X -> HTML PLC documentation pipeline."""


@main.command()
@click.argument("acd", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", "output", type=click.Path(path_type=Path), default=None,
              help="Output .L5X path (default: next to the source ACD).")
@click.option("--reference", "reference", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="Optional Studio-exported L5X to diff the conversion against.")
def convert(acd: Path, output, reference):
    """Convert an .ACD file to .L5X (offline, no Studio 5000 SDK)."""
    result = pipeline.convert(acd, l5x_path=output, reference_path=reference)
    if not result.get("success"):
        click.echo(f"Error: {result.get('error', 'conversion failed')}", err=True)
        sys.exit(1)
    click.echo(f"[OK] Converted: {result.get('l5x_path')}")


@main.command()
@click.argument("l5x", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("-o", "--output", "output", type=click.Path(path_type=Path), default=None,
              help="Output directory (default: l5x_individual/ next to the source L5X).")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Print verbose output.")
def split(l5x: Path, output, verbose):
    """Split a monolithic .L5X file into per-routine XML files + index/xref."""
    result = pipeline.split(l5x, out_dir=output, verbose=verbose)
    if not result.get("success"):
        click.echo(f"Error: {result.get('error', 'split failed')}", err=True)
        sys.exit(1)
    click.echo(f"[OK] Split output: {result.get('out_dir')}")


@main.command(name="document")
@click.argument("input_path", metavar="FILE_OR_DIR",
                 type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", "output", type=click.Path(path_type=Path), default=None,
              help="Output directory (default: next to source file(s)).")
@click.option("-t", "--translate", "translate_override", flag_value=True, default=None,
              help="Force bilingual (Italian+English) output.")
@click.option("--no-translate", "translate_override", flag_value=False,
              help="Force English-only output, even for a Colussi/Vemac path.")
@click.option("--online-translate", "use_online", is_flag=True, default=False,
              help="Enable the online (deep-translator) MT fallback for bilingual output.")
@click.option("--no-index", is_flag=True, default=False,
              help="Skip generating index.html when documenting a directory.")
@click.option("--inline-assets", is_flag=True, default=False,
              help="Embed JS/CSS assets directly into each HTML file.")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Print verbose output.")
def document(input_path: Path, output, translate_override, use_online, no_index,
             inline_assets, verbose):
    """Generate HTML documentation from an L5X file or a directory of them.

    Bilingual (Italian+English) output is auto-detected PER FILE from each
    L5X's source path (Colussi/Vemac integrators) unless overridden with
    -t/--translate or --no-translate.
    """
    result = pipeline.document(
        input_path,
        output=output,
        translate_override=translate_override,
        use_online=use_online,
        no_index=no_index,
        inline_assets=inline_assets,
        verbose=verbose,
    )
    if not result.get("success"):
        click.echo(f"Error: {result.get('error', 'documentation failed')}", err=True)
        sys.exit(1)
    generated = result.get("generated") or []
    click.echo(f"[OK] Generated {len(generated)} documentation file(s)")
    if result.get("index"):
        click.echo(f"[INDEX] Index: {result['index']}")


@main.command(name="run")
@click.argument("acd", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--skip-split", is_flag=True, default=False, help="Skip stage 2 (split).")
@click.option("--skip-doc", is_flag=True, default=False, help="Skip stage 3 (document).")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Print verbose output.")
def run(acd: Path, skip_split, skip_doc, verbose):
    """Run the full pipeline (convert -> split -> document) for one .ACD file."""
    result = pipeline.run_full(acd, verbose=verbose, skip_split=skip_split, skip_doc=skip_doc)
    if not result.get("success"):
        click.echo(f"Error: {result.get('error', 'pipeline failed')}", err=True)
        sys.exit(1)
    click.echo(f"[OK] Full pipeline complete for: {acd}")


@main.command()
@click.option("--since", "since_ref", required=True, help="Git ref to diff from.")
@click.option("--repo", "repo_root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path("."), help="Repository root (default: current directory).")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Print verbose output.")
def regenerate(since_ref, repo_root, verbose):
    """Re-run the full pipeline only for .ACD files changed since a git ref."""
    result = pipeline.regenerate_changed(since_ref, repo_root, verbose=verbose)
    if not result.get("success"):
        click.echo(f"Error: {result.get('error', 'regeneration failed')}", err=True)
        sys.exit(1)
    click.echo(f"[OK] Regenerated {len(result.get('changed', []))} changed ACD file(s)")


if __name__ == "__main__":
    main()
