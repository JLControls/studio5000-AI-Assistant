# -*- coding: utf-8 -*-
"""
STEP 3 of the comment-authoring workaround (the actual MCP bypass).

Purpose: render the four Studio 5000 deliverables (Comment_Delta.CSV,
comment_review_report.html, decisions.json, comment_memory.json) from the
merged 229-row decision list.

WHY THIS BYPASSES THE MCP TOOL
------------------------------
The intended final step is the MCP tool `generate_comment_deliverables`, which
takes the entire `decisions` array *inline* as a call argument and has no
file-input parameter. For a whole-program run that array is ~69 KB / 229 items,
which is impractical to embed in a single tool call reliably. So instead we
import the *same* pipeline the MCP tool wraps and call it directly, loading the
decisions from disk.

This is the identical code path used by the server:
    tag_mcp_integration.generate_comment_deliverables()
        -> PLCCommentPipeline().generate_deliverables(...)

Requirements: run with the studio5000 server's virtualenv so the tag_analyzer
package and its deps import cleanly:

    $env:PYTHONPATH   = "F:\\git\\work\\studio5000-AI-Assistant\\src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:STUDIO5000_SDK_ENABLED = "false"
    & "F:\\git\\work\\studio5000-AI-Assistant\\venv\\Scripts\\python.exe" 3_render_deliverables.py

Input : ./decisions.authored.json   (from step 2)
        <deliverables>/../ModernTHAWROOM021722.ACD  (or its .L5X export)
Output: the four deliverables written into <deliverables>/
"""
import json
import os
import sys

# The pipeline lives in the studio5000 server source tree. PYTHONPATH must point
# at F:\git\work\studio5000-AI-Assistant\src (set in the env before launching).
try:
    from tag_analyzer.comment_pipeline import PLCCommentPipeline
except ModuleNotFoundError:
    sys.stderr.write(
        "ERROR: tag_analyzer not importable. Run this with the studio5000 server venv "
        "and PYTHONPATH=F:\\git\\work\\studio5000-AI-Assistant\\src\n")
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
DELIVERABLES = os.path.dirname(HERE)
MIGRATED = os.path.dirname(DELIVERABLES)

DECISIONS = os.path.join(HERE, "decisions.authored.json")
ACD = os.path.join(MIGRATED, "ModernTHAWROOM021722.ACD")
PROJECT_NAME = "ModernTHAWROOM021722"


def main():
    decisions = json.load(open(DECISIONS, encoding="utf-8"))
    sys.stderr.write("loaded %d decisions\n" % len(decisions))

    pipeline = PLCCommentPipeline()  # no constructor args
    res = pipeline.generate_deliverables(
        decisions=decisions,
        output_dir=DELIVERABLES,
        project_name=PROJECT_NAME,
        file_path=ACD,          # resolves to the sibling .L5X export for parsing
        edit_acd=False,         # set True only if an updated .ACD is also wanted
    )
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
