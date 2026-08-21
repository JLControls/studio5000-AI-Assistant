# Agent Handoff Prompt: Implementing the Studio 5000 AI Assistant Backlog

Copy and paste the prompt below into the next AI assistant / agent session to begin execution of the engineering audit findings.

---

```markdown
You are an expert industrial controls engineer, Studio 5000 Logix Designer specialist, and Python systems engineer working on:
https://github.com/JLControls/studio5000-AI-Assistant

## 1. Ground Truth & Mandatory Reading

Before touching any code or creating branches, you MUST read:
1. `AGENTS.md` — Pay special attention to the `src`-on-path convention (packages are imported bare, e.g. `from l5x_analyzer import ...`, NOT `from src.l5x_analyzer import ...`).
2. `docs/ENGINEERING_AUDIT_2026.md` — The complete authoritative engineering review, containing line citations, reproduction scenarios, root-cause analyses, and the implementation backlog.

Verify your environment before beginning:
```bash
# Verify Python version (CPython 3.12 is required)
python --version   # or ./venv/bin/python --version

# Run full test suite (must show 238 passed)
python -m pytest   # or ./venv/bin/python -m pytest

# Run server smoke test
python src/mcp_server/studio5000_mcp_server.py --test
```

---

## 2. Immediate Execution Priority: Sprint 1 (P0/P1 Fixes & Core Primitives)

Work on the following tasks in priority order. For each task, create focused commits, write/update pytest unit tests under `tests/`, and verify that the full test suite passes.

### Task 1: Fix `patch_rungs` `@HEX@` Substitution for Newly Introduced Tags (P0 Bug)
* **GitHub Issue:** [#34](https://github.com/JLControls/studio5000-AI-Assistant/issues/34) (BUG-01)
* **File to modify:** `src/acd/zip/write_dat.py` (symbol: `_restore_tag_refs`)
* **Problem:** `_restore_tag_refs()` scopes its substitution map strictly to `@HEX@` object IDs that appeared in the *original* raw rung text. If an edited rung introduces a tag that was not in the original rung, its name is left as plaintext ASCII in `SbRegion.Dat` instead of being converted to `@HEX_OBJECT_ID@`, corrupting the `.ACD` file.
* **Fix:** Invert the global `id_to_name` map (`{name: oid for oid, name in id_to_name.items()}`), tokenize the ladder logic stream to avoid matching instruction opcodes, and replace all recognized project tag names longest-first with `@HEX@`.
* **Tests:** Add a regression test in `tests/acd/test_regn_link.py` (or new test file) that patches a rung with a newly introduced tag and verifies that every tag token in the rebuilt FAFA payload is formatted as `@([A-Za-z0-9]+)@`.

### Task 2: Build Deterministic AST Tag Cross-Reference Engine (Top Feature)
* **GitHub Issue:** [#26](https://github.com/JLControls/studio5000-AI-Assistant/issues/26) & [#12](https://github.com/JLControls/studio5000-AI-Assistant/issues/12) (BUG-03)
* **Files to create/modify:** `src/l5x_analyzer/tag_cross_reference.py`, `src/l5x_analyzer/l5x_mcp_integration.py`, `src/l5x_analyzer/l5x_vector_db.py`, `src/tag_analyzer/tag_mcp_integration.py`
* **Problem:** `find_related_components` and `find_related_tags` query FAISS with synthetic English strings (`"uses <tag>"`), returning false-empty results (`success: true, related_count: 0`) on heavily used tags like `Htr1_Outlet_Temp`.
* **Fix:**
  1. Create a deterministic parser that tokenizes RLL logic (`XIC`, `XIO`, `OTE`, `MOV`, `SCP`, `JSR`, AOI invocations, etc.) and Structured Text statements to build an exact cross-reference index:
     - `tag_name`, `scope` (Controller vs Program), `program`, `routine`, `rung_number`, `instruction`, `operand_index`, `role` (`READ_SOURCE`, `WRITE_DESTINATION`, `READ_WRITE`, `AOI_ARG`).
  2. Wire `find_tag_references(tag_name, program_scope=None)` as a first-class MCP tool.
  3. Update `find_related_components` and `find_related_tags` to delegate to this deterministic AST index instead of FAISS semantic search.
* **Tests:** Add unit tests verifying that querying `Htr1_Outlet_Temp` on `Kemco_HA105.L5X` returns all 11 known references across scaling and control routines.

### Task 3: Add Automated GitHub Actions CI Workflow
* **GitHub Issue:** [#35](https://github.com/JLControls/studio5000-AI-Assistant/issues/35) (BUG-10)
* **File to create:** `.github/workflows/ci.yml`
* **Fix:** Add a GitHub Actions workflow running on `ubuntu-latest` with Python 3.12 that installs `requirements.txt` and executes `python -m pytest -v`.

### Task 4: Fix `get_project_overview` Wrong-Project Fallback (P1 Bug)
* **GitHub Issue:** [#37](https://github.com/JLControls/studio5000-AI-Assistant/issues/37) (BUG-04)
* **File to modify:** `src/l5x_analyzer/l5x_mcp_integration.py` (lines 744–754)
* **Problem:** When a requested project is unindexed or missing from cache, the tool falls back to `list(indexed_projects.keys())[0]` and returns the overview of an unrelated project.
* **Fix:** Return `success: False` with an explicit error message naming the missing project and instructing the caller to run `index_exported_l5x_files` or `index_acd_project`.
* **Tests:** Add unit test in `tests/l5x_analyzer/test_project_overview.py` confirming error return on unindexed project request.

### Task 5: Redirect Stray Stdout Print Statements to Stderr (P2 Bug)
* **GitHub Issue:** [#38](https://github.com/JLControls/studio5000-AI-Assistant/issues/38) (BUG-06)
* **File to modify:** `src/code_generator/l5x_generator.py` (lines 326, 393, 469–474)
* **Fix:** Redirect all `print(...)` error statements to `file=sys.stderr` or use standard `logging` to avoid corrupting the MCP stdio JSON-RPC protocol stream.

### Task 6: Support Target Program Context in `generate_routine_export` (P2 Bug)
* **GitHub Issue:** [#39](https://github.com/JLControls/studio5000-AI-Assistant/issues/39) (BUG-07)
* **File to modify:** `src/code_generator/l5x_generator.py` (lines 329–372), `src/mcp_server/studio5000_mcp_server.py`
* **Fix:** Accept `program_name: str = "MainProgram"` and emit `<Program Use="Context" Name="{program_name}" ...>` in the L5X routine export template.

### Task 7: Retain Isolated Raw Analog Aliases in Ignition Exporter
* **GitHub Issue:** [#10](https://github.com/JLControls/studio5000-AI-Assistant/issues/10)
* **File to modify:** `src/ignition_exporter/ignition_mcp_integration.py` (`_collect_export_items`)
* **Fix:** When pruning raw analog aliases, check whether a scaled engineering counterpart exists. If none exists, retain the raw alias and mark it as an unscaled process point with advisory metadata.

### Task 8: Secure Vector Caches by Replacing `pickle.load()` (P1 Security Bug)
* **GitHub Issue:** [#36](https://github.com/JLControls/studio5000-AI-Assistant/issues/36) (BUG-05)
* **Files to modify:** `src/documentation/instruction_vector_db.py`, `src/l5x_analyzer/l5x_vector_db.py`, `src/tag_analyzer/tag_vector_db.py`, `src/drawings_analyzer/pdf_vector_db.py`, `src/sdk_documentation/sdk_vector_db.py`, `src/mcp_server/studio5000_mcp_server.py`
* **Fix:** Replace `.pkl` loading with `safetensors` or `numpy.save()` for embedding arrays and JSON/JSONL for chunk metadata.

---

## 3. Engineering Guidelines & Quality Standards

- **Strict Import Convention:** Always use bare imports (`from l5x_analyzer import ...`, `from comment_graph import ...`), never `from src.l5x_analyzer ...`.
- **Zero Regression Tolerance:** Run `python -m pytest` and `python src/mcp_server/studio5000_mcp_server.py --test` after every tool or subsystem modification.
- **GitHub Issue Updates:** When you complete a task, use `gh issue comment <id>` and `gh issue close <id>` to keep the project backlog synchronized.
- **Code Style:** 4-space indentation, clear type annotations, small focused functions, no unvalidated heuristics masquerading as deterministic facts.
```
