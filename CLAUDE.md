# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Process, style, and PR conventions live in `.claude/CLAUDE.md` / `AGENTS.md`. This file
> focuses on commands and the cross-file architecture. **Studio 5000 v38 L5X semantics are the
> target**; the live Studio 5000 SDK is disabled by default (see "SDK gating" below).

## Environment & Commands

Windows, **Python 3.12** (not 3.11/3.14 — the shell may resolve `python` to a 3.14 venv; tests
are validated on 3.12). Run everything from the repo root.

```powershell
python -m pip install -r requirements.txt

# MCP server smoke test (indexes docs, runs sample queries incl. analyze_comment_graph). ALWAYS run this.
python src/mcp_server/studio5000_mcp_server.py --test
python src/mcp_server/studio5000_mcp_server.py --doc-root "<Studio 5000 help path>" --test   # explicit doc root if auto-detect fails

# Tests — src/ must lead sys.path. conftest.py (repo root) handles this, so plain pytest works:
python -m pytest
python -m pytest tests/comment_graph/test_orchestrator.py           # single file
python -m pytest tests/comment_graph/test_orchestrator.py::test_x   # single test
python -m pytest tests/acd/                                          # ACD/comment regression suite
```

No build step, linter, or formatter is configured. There is no coverage threshold.

### The `src`-on-path convention (important)

Packages are imported bare (`from l5x_analyzer... import ...`, `from comment_graph... import ...`),
**not** as `src.l5x_analyzer`. This works because:
- The MCP server does `sys.path.append('..')` at startup (`studio5000_mcp_server.py:25`).
- The root `conftest.py` **prepends** `src` to `sys.path` for pytest.

The prepend also makes the **vendored `src/acd`** shadow a stale `acd_tools` package that may be
installed in the venv's site-packages. If you see the wrong `acd` being imported, that's the cause —
don't "fix" it by renaming imports; keep `src` leading the path.

## Architecture

This is an **MCP server** (`src/mcp_server/studio5000_mcp_server.py`, ~2100 lines) that exposes
~40 tools for PLC programming assistance. It speaks JSON-RPC over stdio and is launched by an MCP
client (Claude Desktop) via `mcp_config.json`.

### MCP server shape
- `MCPServer` is a **hand-rolled** minimal server class (not the `mcp` SDK) — `add_tool(name, description, handler)` registers into a dict; `handle_mcp_request` dispatches JSON-RPC.
- `Studio5000MCPServer._register_tools()` is the single source of truth for the tool surface. Adding a tool = a handler method + one `add_tool` call + its `inputSchema` in the `list_tools` response section.
- **Lazy init**: `_register_tools()` is intentionally lightweight — vector DBs (FAISS) index on first use, not at startup, so `--test` stays fast.
- Domain logic lives in the per-domain packages; the server file is mostly a thin delegation layer. Each domain ships an `*_mcp_integration.py` that adapts its engine to MCP tool calls.

### Domain packages (`src/`)
- `documentation/` + `sdk_documentation/` — Studio 5000 instruction & SDK docs, semantic search (FAISS + sentence-transformers). Backs `search_instructions`, `get_instruction*`, `list_categories`.
- `code_generator/` — natural language → ladder logic → L5X (`L5XGenerator`, `L5XProject/Program/Routine/LadderRung`). Backs `generate_ladder_logic`, `create_l5x_project`, `create_l5x_routine`.
- `l5x_analyzer/` — semantic search / surgical rung insertion / structure analysis over large exported L5X. Backs `search_l5x_content`, `find_insertion_point`, `smart_insert_logic`, `analyze_routine_structure`.
- `drawings_analyzer/` — PDF engineering drawings (PyMuPDF/pdfplumber) → search + equipment cross-reference.
- `tag_analyzer/` — CSV tag DB parsing + vector search + the **comment pipeline** (`comment_pipeline.py`, ~52k lines is the heavyweight). Backs tag/device/I-O tools, `get_uncommented_tags`, `generate_comment_deliverables`, `manage_comment_memory`.
- `ladder_renderer/`, `verification/` — render RLL and validate ladder syntax (`_validate_ladder_syntax`); `LadderInstruction.get_primary_tag()`.
- `acd/` — **vendored** patched ACD parser/exporter (Kaitai-based, `generated/` = Kaitai output). `api.py` is the entry point: `load_acd`, `save_acd`, `patch_rungs`, `ExportProjectToFile` (XML `pretty_print=True` by default). Backs `convert_acd_to_l5x`, `index_acd_project`. This targets v38 L5X and is used **instead of** the live SDK for offline analysis.
- `sdk_interface/` — live Studio 5000 SDK bindings, **gated off by default**.

### comment_graph (`src/comment_graph/`) — the newest subsystem
Iterative PLC comment analysis engine: builds a **typed dependency graph** of tags/instructions and
runs a monotonic fact-propagation loop to propose comments. Pure library (no MCP/asyncio coupling
except the executor). Backs the `analyze_comment_graph` tool. Design doc:
`docs/superpowers/plans/2026-08-05-iterative-comment-analysis-plan.md`.

Module pipeline (each has a matching test in `tests/comment_graph/`):
`builder.py` (graph construction, base-tag linking) → `edges.py` (typed edges; mnemonic aliasing,
e.g. `MOVE→MOV`, `LT→LES`, `GE→GEQ`; r/w direction is deterministic from instruction param
position) → `graph_adapter.py` (networkx wrapper) → `model.py` (dataclasses) → `facts.py`
(dedup'd monotonic fact store) → `scheduler.py` (SCC-aware topo queue) → `worker.py` (deterministic
per-node reasoning) → `orchestrator.py` (bounded async executor: gather → sort → merge each pass) →
`deliverables_bridge.py` (results → the comment-deliverables format shared with `tag_analyzer`).
`is_placeholder`/`_seed` filtering treats migration-generated placeholder comments as uncommented so
they become proposal candidates.

### SDK gating
`SDK_ENABLED = STUDIO5000_SDK_ENABLED in {1,true,yes}` (default **false**). When off,
`sdk_interface`/`sdk_documentation` SDK imports are skipped and the `create_acd_project` +
`*_sdk_*` tools are not registered. Offline ACD work goes through the vendored `src/acd` parser
instead. Don't assume the live SDK is present.

## Gotchas
- **Never commit** proprietary `.ACD`/`.L5X`/`.L5K`/PDF files, vector caches (`*_vector_cache/`, `*.pkl`, `*.faiss`), `*.log`, or machine-specific paths. `.gitignore` blocks root-level `/test_*.py` and `/debug_*.py` scratch scripts — but the real suite under `tests/` is **not** ignored (note the leading slash).
- `mcp_config.json` contains machine-specific absolute paths (a `sourceRepo/` layout) — review before staging; it's an example, not necessarily your local layout.
- Two L5X fixtures live at the repo root (`upstream-patched-test.L5X`, `v38-fixed-test.L5X`) for v38 parity work; the canonical regression fixtures are under `tests/acd/`.
- Generated PLC logic requires engineering review + Studio 5000 validation before use on real hardware.
