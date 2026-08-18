# AGENTS.md

This file provides guidance to Claude Code, AGY, and other AI assistants working in this repository.

## Project Summary & Structure

Production code lives in `src/`, split by responsibility:
- `mcp_server/` (`src/mcp_server/studio5000_mcp_server.py`, ~2400 lines) — Minimal hand-rolled MCP server exposing 52 tools for PLC programming assistance over stdio JSON-RPC (`mcp_config.json`).
- `documentation/` + `sdk_documentation/` — Studio 5000 instruction & SDK docs, semantic search (FAISS + sentence-transformers). Backs `search_instructions`, `get_instruction*`, `list_categories`.
- `code_generator/` — Natural language → ladder logic → L5X (`L5XGenerator`, `L5XProject/Program/Routine/LadderRung`). Backs `generate_ladder_logic`, `create_l5x_project`, `create_l5x_routine`.
- `l5x_analyzer/` — Semantic search / surgical rung insertion / structure analysis over large exported L5X. Backs `search_l5x_content`, `find_insertion_point`, `smart_insert_logic`, `analyze_routine_structure`.
- `drawings_analyzer/` — PDF engineering drawings (PyMuPDF/pdfplumber) → search + equipment cross-reference.
- `tag_analyzer/` — CSV tag DB parsing + vector search + the comment pipeline (`comment_pipeline.py`). Backs tag/device/I-O tools, `get_uncommented_tags`, `generate_comment_deliverables`, `manage_comment_memory`.
- `ladder_renderer/`, `verification/` — Render RLL and validate ladder syntax (`_validate_ladder_syntax`); `LadderInstruction.get_primary_tag()`.
- `acd/` — Vendored patched ACD parser/exporter (Kaitai-based). `api.py` is the entry point (`load_acd`, `save_acd`, `patch_rungs`, `ExportProjectToFile`). Used for offline analysis targeting Studio 5000 v38 L5X semantics.
- `sdk_interface/` — Live Studio 5000 SDK bindings, **gated off by default**.
- `comment_graph/` (`src/comment_graph/`) — Iterative PLC comment analysis engine: builds a typed dependency graph (`builder.py`, `edges.py`, `graph_adapter.py`, `facts.py`, `scheduler.py`, `worker.py`, `orchestrator.py`, `deliverables_bridge.py`) and runs a monotonic fact-propagation loop to propose comments. Pure library backing the `analyze_comment_graph` tool. See `docs/superpowers/plans/2026-08-05-iterative-comment-analysis-plan.md`.

Automated tests belong under `tests/` (including ACD regression tests under `tests/acd/`). Design notes belong in `docs/superpowers/`; user-facing workflows are documented in root-level guides.

## Environment & Development Commands

Use Windows with **Python 3.12** (tests are validated on 3.12; verify `python` does not resolve to 3.11/3.14 venv) and Studio 5000 Logix Designer v36 or later. Run all commands from the repo root:

```powershell
# Install dependencies
python -m pip install -r requirements.txt

# MCP server smoke test (indexes docs, runs sample queries incl. analyze_comment_graph). ALWAYS run this.
python src/mcp_server/studio5000_mcp_server.py --test
python src/mcp_server/studio5000_mcp_server.py --doc-root "<Studio 5000 help path>" --test   # explicit doc root if auto-detect fails

# Tests — src/ must lead sys.path (handled automatically by tests/conftest.py):
python -m pytest
python -m pytest tests/comment_graph/test_orchestrator.py           # single file
python -m pytest tests/comment_graph/test_orchestrator.py::test_x   # single test
python -m pytest tests/acd/                                          # ACD/comment regression suite
```

No separate build system, linter, or formatter is configured. There is no coverage threshold.

### The `src`-on-path Convention

Packages are imported bare (`from l5x_analyzer... import ...`, `from comment_graph... import ...`), **not** as `src.l5x_analyzer`.
- The MCP server prepends/appends `src` to `sys.path` (`studio5000_mcp_server.py:25`).
- `tests/conftest.py` prepends `src` to `sys.path` for pytest before any test is imported.
- This prepend also ensures the vendored `src/acd` shadows any stale `acd_tools` package installed in site-packages. Keep `src` leading the path rather than renaming imports.

## Architecture & System Design

### MCP Server Shape
- `MCPServer` is a hand-rolled minimal server class (not the `mcp` SDK) — `add_tool(name, description, handler)` registers tools; `handle_mcp_request` dispatches JSON-RPC requests.
- `Studio5000MCPServer._register_tools()` is the single source of truth for the tool surface. Adding a tool requires a handler method, an `add_tool` registration, and its `inputSchema` in `list_tools`.
- **Lazy initialization**: `_register_tools()` is lightweight — FAISS vector databases index on first use, keeping `--test` fast.
- Domain logic stays in respective `src/` packages; the server file is a thin delegation layer using `*_mcp_integration.py` adapters.

### SDK Gating
`SDK_ENABLED = STUDIO5000_SDK_ENABLED in {1,true,yes}` (default **false**). When disabled:
- `sdk_interface` / `sdk_documentation` SDK imports are skipped.
- `create_acd_project` and `*_sdk_*` tools are not registered.
- Offline ACD work uses the vendored `src/acd` parser instead.

## Coding Style & Naming Conventions

- **Python Conventions**: 4-space indentation, `snake_case` for modules, functions, and variables, `PascalCase` for classes.
- **Modularity**: Keep package boundaries clear and prefer small, single-purpose helpers.
- **Consistency**: Match surrounding code before introducing new abstractions; avoid unrelated reformatting.

## Testing & Verification Guidelines

- Add focused `pytest` tests under `tests/` using `test_*.py` filenames.
- Always run `python src/mcp_server/studio5000_mcp_server.py --test` after tool or server changes.
- Validate generated L5X or ACD output in Studio 5000 Logix Designer v36+ when applicable.

## Commits & Pull Requests

- Use concise imperative commit subjects, optionally scoped with a subsystem prefix (e.g., `PLC: add ...` or `Update ...`).
- Keep commits focused and atomic.
- PRs should explain behavior changes, affected paths, validation commands/results, and Studio 5000/SDK version assumptions. Include representative output samples or screenshots for PLC/ladder logic changes.

## Security, Configuration & Gotchas

- **Do Not Commit**: Credentials, proprietary `.ACD`/`.L5X`/`.L5K`/PDF files, machine-specific paths, vector caches (`*_vector_cache/`, `*.pkl`, `*.faiss`), `*.log`, or debug dumps.
- **Scratch Scripts**: `.gitignore` blocks root-level `/test_*.py` and `/debug_*.py` scratch scripts — but the real test suite under `tests/` is tracked.
- **Config Review**: Review `mcp_config.json` before staging (contains local path examples).
- **Parity Fixtures**: Root L5X files (`upstream-patched-test.L5X`, `v38-fixed-test.L5X`) are for v38 parity work; canonical regression fixtures belong under `tests/acd/`.
- **Engineering Review**: Treat generated PLC logic as requiring engineering review and Studio 5000 validation before deployment to live control systems.
