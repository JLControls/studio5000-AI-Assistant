# Repository Guidelines

## Project Structure

Production code lives in `src/`, split by responsibility: `mcp_server` exposes the MCP server; `l5x_analyzer`, `tag_analyzer`, `drawings_analyzer`, and `sdk_documentation` provide domain parsing/search; `code_generator`, `ladder_renderer`, and `ai_assistant` generate or present PLC logic; `sdk_interface` contains Studio 5000 integration; and `acd` is the vendored ACD parser/exporter. Put automated tests in `tests/`, including ACD regression tests under `tests/acd/`. Design notes belong in `docs/superpowers/`; user-facing workflows are documented in the root-level guides. Keep generated/debug artifacts and local configuration out of commits.

## Build, Test, and Development Commands

Use Windows with Python 3.12 and Studio 5000 Logix Designer v36 or later. From the repository root:

```powershell
python -m pip install -r requirements.txt
python src/mcp_server/studio5000_mcp_server.py --test
python src/mcp_server/studio5000_mcp_server.py --doc-root "<Studio 5000 help path>" --test
```

The first command installs dependencies; the second runs the documented server smoke test and auto-detects local Studio 5000 paths; the last supplies an explicit documentation root when detection fails. No separate build system or formatter is configured.

## Coding Style and Naming

Follow existing Python conventions: four-space indentation, `snake_case` for modules, functions, and variables, and `PascalCase` for classes. Keep package boundaries clear and prefer small, single-purpose helpers. Match surrounding code before introducing new abstractions, and avoid unrelated reformatting.

## Testing Guidelines

There is no coverage threshold. Add focused `pytest` tests under `tests/` using `test_*.py` filenames, then run `python -m pytest` with `PYTHONPATH=src`. Always run the MCP `--test` smoke test; validate generated L5X or ACD output in Studio 5000 when applicable.

## Commits and Pull Requests

Use concise imperative commit subjects, optionally scoped with a subsystem prefix, such as `PLC: add ...` or `Update ...`. Keep commits focused. PRs should explain the behavior change, affected paths, validation commands and results, and any Studio 5000/SDK version assumptions. Include representative generated-output samples or screenshots when they clarify PLC or ladder changes, and link the relevant issue or design note.

## Security and Configuration

Do not commit credentials, proprietary ACD/L5X/PDF files, machine-specific paths, caches, or debug dumps. Review `mcp_config.json` and generated PLC artifacts before staging. Treat generated logic as requiring engineering review and Studio 5000 validation before use in a control system.
