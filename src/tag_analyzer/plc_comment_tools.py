#!/usr/bin/env python3
"""
CLI Wrapper for PLC Comment Maintenance Pipeline

Provides command-line interfaces for:
- get-uncommented-tags
- get-tag-reasoning-context
- generate-deliverables
- manage-memory
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path if executed as script
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from tag_analyzer.comment_pipeline import PLCCommentPipeline


def main():
    parser = argparse.ArgumentParser(description="PLC Comment Pipeline CLI Tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # get-uncommented-tags
    p_unc = subparsers.add_parser("get-uncommented-tags", help="Get list of uncommented tags")
    p_unc.add_argument("--file", required=True, help="Path to ACD or L5X file")
    p_unc.add_argument("--scope", help="Optional scope filter (Routine, Program, or Controller)")

    # reasoning-context
    p_ctx = subparsers.add_parser("get-tag-reasoning-context", help="Extract project-wide context for a tag")
    p_ctx.add_argument("--file", required=True, help="Path to ACD or L5X file")
    p_ctx.add_argument("--tag", required=True, help="Tag or operand name")

    # generate-deliverables
    p_del = subparsers.add_parser("generate-deliverables", help="Generate CSV delta and HTML audit report")
    p_del.add_argument("--decisions", required=True, help="Path to decisions.json")
    p_del.add_argument("--output-dir", required=True, help="Output directory")
    p_del.add_argument("--project-name", default="ModernTHAWROOM021722", help="Project name")

    # manage-memory
    p_mem = subparsers.add_parser("manage-memory", help="Update object-level comment memory")
    p_mem.add_argument("--file", required=True, help="Path to ACD or L5X file")
    p_mem.add_argument("--memory-file", required=True, help="Path to memory.json")
    p_mem.add_argument("--decisions", help="Path to decisions.json")

    args = parser.parse_args()
    pipeline = PLCCommentPipeline()

    if args.command == "get-uncommented-tags":
        res = pipeline.get_uncommented_tags(args.file, args.scope)
        print(json.dumps(res, indent=2))

    elif args.command == "get-tag-reasoning-context":
        res = pipeline.get_tag_reasoning_context(args.tag, args.file)
        print(json.dumps(res, indent=2))

    elif args.command == "generate-deliverables":
        dec_path = Path(args.decisions)
        decisions = json.loads(dec_path.read_text(encoding="utf-8"))
        res = pipeline.generate_deliverables(decisions, args.output_dir, args.project_name)
        print(json.dumps(res, indent=2))

    elif args.command == "manage-memory":
        decisions = None
        if args.decisions:
            dec_path = Path(args.decisions)
            if dec_path.exists():
                decisions = json.loads(dec_path.read_text(encoding="utf-8"))
        res = pipeline.manage_incremental_memory(args.file, args.memory_file, decisions)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
