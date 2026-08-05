# MCP workaround scripts — ModernTHAWROOM021722 comment generation

These are the scripts used to generate the comment deliverables in the parent
folder when the studio5000 MCP tools couldn't carry the whole-program run on
their own. They reproduce the four deliverables exactly and are the reference
for the fixes in `IMPROVEMENTS.md`.

## The three steps

| # | Script | Runs with | In → Out |
|---|--------|-----------|----------|
| 1 | `1_dump_work_packet.py` | any Python 3.8+ | `../work_packet.json` → `dumps/dump_<Routine>.txt` |
| 2 | `2_author_comments.py` | any Python 3.8+ | `../work_packet.json` → `decisions.authored.json` (229 rows) |
| 3 | `3_render_deliverables.py` | **studio5000 server venv** | `decisions.authored.json` → `../Comment_Delta.CSV` + `.html` + `decisions.json` + `comment_memory.json` |

Step 3 must use the server's virtualenv because it imports the server's
`tag_analyzer` pipeline:

```powershell
$env:PYTHONPATH   = "F:\git\work\studio5000-AI-Assistant\src"
$env:PYTHONIOENCODING = "utf-8"
$env:STUDIO5000_SDK_ENABLED = "false"
& "F:\git\work\studio5000-AI-Assistant\venv\Scripts\python.exe" .\3_render_deliverables.py
```

Steps 1 and 2 run with any Python.

## What each step is standing in for

- **Step 1** — makes the orchestrator's oversized `to_resolve` list readable
  (works around MCP result-size limits; see IMPROVEMENTS P4).
- **Step 2** — authors the escalated comments from the ladder logic and merges
  them with the auto-decisions (works around the missing "fill-the-packet"
  round-trip; see IMPROVEMENTS P1/P2). **This is the file that contains the
  actual comment text that was authored.**
- **Step 3** — renders the deliverables by calling the pipeline directly instead
  of through the MCP tool, whose `decisions` argument can't take a 69 KB list
  (the core blocker; see IMPROVEMENTS P1).

## Provenance / upstream

The work packet came from the MCP call
`generate_program_comments(acd_path="…/ModernTHAWROOM021722.ACD")`.
Pipeline source: `F:\git\work\studio5000-AI-Assistant\src\tag_analyzer\`
(`comment_pipeline.py`, `tag_mcp_integration.py`).

See `IMPROVEMENTS.md` for the ranked list of server changes that would let the
next run stay entirely inside the MCP tools.
