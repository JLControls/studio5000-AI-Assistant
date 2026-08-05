# Studio 5000 MCP — improvements needed

Context: generating logic + tag comments for the whole `ModernTHAWROOM021722`
program (229 decisions) required stepping outside the MCP tools three times. The
scripts in this folder are the workaround. Below is what needs to change in the
server (`F:\git\work\studio5000-AI-Assistant\src`) so the next whole-program run
can stay entirely inside the MCP tools.

Ranked by how much friction each one caused.

---

## P1 — `generate_comment_deliverables` has no file-input for `decisions` (the blocker)

**Symptom.** The final render step wants the complete decision list passed
*inline* as the `decisions` array argument. For this program that is 229 items /
~69 KB. Embedding that in a single MCP tool call is impractical and unreliable
(the reader/writer truncates around 25–40 k tokens), so the MCP path can't finish
a whole-program run. I bypassed it by importing `PLCCommentPipeline` and calling
`generate_deliverables()` directly (see `3_render_deliverables.py`).

**Fix.** Add an optional `decisions_path` parameter (JSON file on disk) to
`generate_comment_deliverables` (and its `tag_mcp_integration` wrapper):
```
async def generate_comment_deliverables(self, decisions=None, decisions_path=None, ...):
    if decisions is None and decisions_path:
        decisions = json.load(open(decisions_path, encoding="utf-8"))
```
Make `decisions` / `decisions_path` mutually exclusive; error if both/neither.
This single change removes the need for the direct-pipeline bypass entirely.

**Better still.** See P2 — let it read the work packet directly.

---

## P2 — No "fill the work packet and render" round-trip

**Symptom.** The workflow is: `generate_program_comments` writes
`work_packet.json` (with `auto_decisions` + `to_resolve[].draft_decision`
skeletons) → the model fills each `draft_decision.PROPOSED_DESCRIPTION` → the
model must then **manually merge** `auto_decisions` + the filled drafts into one
list and hand it back. That merge (`2_author_comments.py`) is pure plumbing.

**Fix.** Accept the edited work packet directly:
```
generate_comment_deliverables(work_packet_path=<...>/work_packet.json, ...)
```
When given a work packet, the pipeline should render from
`auto_decisions + [it["draft_decision"] for it in to_resolve]`, skipping any
draft whose `PROPOSED_DESCRIPTION` is still blank (and reporting the count
skipped). The model then only edits one file in place — no merge, no re-listing.

---

## P3 — `generate_program_comments` under-declares its input schema

**Symptom.** The tool's advertised JSON schema had `properties: {}` /
`required: []`, but the function actually requires a positional `acd_path`. The
first call failed with:
`generate_program_comments() missing 1 required positional argument: 'acd_path'`.
The parameters (`acd_path`, `routine_filter`, `offset`, `limit`, `config`) are
invisible to the caller until you read the source.

**Fix.** Ensure the MCP tool registration emits the real parameter schema for
`generate_program_comments`. Other tools (`get_project_overview`,
`get_uncommented_tags`) expose `acd_path`/`file_path` correctly, so this is a
per-tool registration gap — likely a missing type-hint-to-schema step or a
decorator that isn't introspecting this function. Audit all tools for the same
gap.

---

## P4 — Large orchestrator result is dumped inline instead of by reference

**Symptom.** `generate_program_comments` returned 56 KB / 1,496 lines and
exceeded the tool-result token cap, forcing a spill to a temp file. Yet the same
call already writes the full list to `work_packet.json` and returns
`work_packet_path`. The inline `auto_decisions` + `to_resolve` arrays are
redundant with the on-disk packet.

**Fix.** When the result is large (or always), return a compact envelope:
`counts`, `page`, `work_packet_path`, `next_steps`, and a small `sample`
(e.g. first 3 `to_resolve`) — not the full arrays. The caller reads
`work_packet.json` for detail. This keeps the orchestrator's result well under
the token cap and removes the pagination dance (`offset`/`limit`) for the common
"give me everything, I'll read the file" case.

---

## P5 — Reasoning-context prefetch misses operands that only appear as instruction *inputs*

**Symptom.** 30 of 209 escalations came back `occurrence_count: 0` /
"no logic evidence", grouped as `NO_EVIDENCE`. But most of them **do** have
evidence — they appear as operands in comparisons and moves in other routines:
- `N101[0]`, `N101[2]`, `N101[19]` — used in `LT/GE/GT` in `Cell_1_Temperature_Control_4`
- `N104[0]`, `N104[2]`, `N104[19]` — same, `Cell_2_Temperature_Control_8`
- `N18[11..16]`, `N18[27..32]`, `N111[18]..N132[18]` — `MOVE` source/dest chains in `Temperature_Input_Scaling_3`

They were flagged as no-evidence because the graph only counted rungs where the
tag is the **output / primary entity**, not rungs where it is any operand
(a `MOVE` source, a comparison operand).

**Fix.** In the rung-reference prefetch, include rungs where the tag appears as
**any** operand of an instruction, not just as the destination. Rank
output-occurrences first, but attach the input-occurrences too. That would have
moved these ~30 items from "guess" to "evidence-backed", and several would have
become `auto_decisions`.

---

## P6 — CSV writer is cp1252 strict; non-cp1252 characters will crash the render

**Symptom (latent).** `generate_deliverables` writes the CSV with
`encoding="cp1252"` and no error handler. This run's descriptions used en-dashes
(U+2013), which cp1252 covers (0x96), so it worked. But any description
containing a character outside cp1252 — e.g. `→` (U+2192), `≥` (U+2265), `≤`,
`µ` is fine but `⁰`/superscripts are not — will raise `UnicodeEncodeError` and
abort the whole render.

**Fix.** Normalize before writing: map the common offenders to ASCII
(`→`→`->`, `≥`→`>=`, `≤`→`<=`, `–`→`-` if you prefer pure ASCII) and/or open with
`errors="replace"` plus a warning that lists which rows were altered. PLC comment
text should not be able to crash the exporter.

---

## P7 — Verify the COMMENT-row column mapping against a real Studio 5000 import

**Symptom (needs validation).** Operand comments are emitted as
`COMMENT` rows with the operand path in the **NAME** column and an empty
**SPECIFIER** column:
```
COMMENT,THAWROOM,B3[0].0,<desc>,,,
```
Studio 5000's native comment import generally expects the base tag in NAME and
the member/bit reference (`[0].0`) in the SPECIFIER column (col 6). If the import
rejects or mis-files these rows, the pipeline needs to split
`NAME` → base tag + specifier for `COMMENT` rows.

**Action.** Do one real round-trip import of `Comment_Delta.CSV` into a scratch
copy of the project and confirm operand comments land on the right operands. If
they don't, fix the column mapping in `generate_deliverables`. (This is the one
item I could not verify without Studio 5000 open.)

---

## P8 — `generate_comment_deliverables` can't parse a bare ACD

**Symptom (minor).** `PLCCommentPipeline.resolve_l5x_path()` requires a
pre-existing `.L5X` next to the `.ACD`; with only an `.ACD` present it raises
"No associated L5X export found… Export to L5X first." The render happened to
find `ModernTHAWROOM021722.L5X`. The orchestrator converts up front, but the
render step alone does not.

**Fix.** Have `generate_deliverables` fall back to `convert_acd_to_l5x` (offline
parser, already in the server) when only an ACD is present, so the step is
self-sufficient.

---

## Net effect if P1–P4 are done

The whole-program flow collapses to three MCP calls with no scripts:
1. `generate_program_comments(acd_path=...)` → writes `work_packet.json`
2. model fills `draft_decision.PROPOSED_DESCRIPTION` in the packet (in place)
3. `generate_comment_deliverables(work_packet_path=...)` → four deliverables

P5 further shrinks step 2 by auto-resolving the input-operand cases.
