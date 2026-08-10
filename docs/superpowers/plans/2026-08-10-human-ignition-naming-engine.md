# Human-readable Ignition Naming Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in deterministic `naming="human"` mode to `generate_ignition_tags` that emits operator-facing Ignition names, descriptions, tooltips, and folders while preserving all technical export fields.

**Architecture:** Extract the Kemco naming prototype into a pure `naming_engine` library with a built-in profile and optional JSON profile extensions. The existing exporter will generate presentation overrides after its normal technical item collection, then reuse the current tag builder and folder-tree assembly. The hand-rolled MCP server will expose the two new arguments while retaining raw naming as the default.

**Tech Stack:** Python 3.12, dataclasses, standard-library JSON/regex/path utilities, existing Ignition exporter, pytest, MCP JSON-RPC schema.

## Global Constraints

- `naming="raw"` remains the default and must preserve existing caller behavior.
- `device_name` remains unchanged in every OPC item path; human naming may change only the display folder root.
- The naming engine is deterministic and uses no LLM, vector DB, or network service.
- Technical fields remain owned by the MCP exporter: OPC paths, data types, scaling, historian settings, selection, and exclusions must not change in human mode.
- Invalid naming modes or malformed profiles must fail before creating an output file.
- Use `F:\git\work\studio5000-AI-Assistant\venv\Scripts\python.exe` for tests.
- Preserve the pre-existing modification to `tests/test_direct_acd_deliverables.py`; never stage or overwrite it.
- Generated PLC/SCADA output still requires engineering review and Ignition validation before deployment.

## File Map

Create:

- `src/ignition_exporter/naming_engine.py` — pure profile, presentation, normalization, routing, and collision logic.
- `tests/ignition_exporter/test_naming_engine.py` — unit tests for the pure engine and profile loader.
- `tests/ignition_exporter/fixtures/kemco_style_corpus.json` — the 143-tag name/folder regression corpus copied from the Kemco engagement.

Modify:

- `src/ignition_exporter/ignition_mcp_integration.py` — generate and merge human presentation metadata without changing technical collection.
- `src/mcp_server/studio5000_mcp_server.py` — handler signature, tool description, and `tools/list` schema.
- `tests/ignition_exporter/test_generate.py` — raw/human integration and technical-parity assertions.
- `tests/ignition_exporter/test_overrides.py` — partial explicit override precedence in human mode.
- `tests/test_mcp_workaround_fixes.py` — MCP schema regression for `naming` and `naming_profile_path`.

Do not modify:

- `tests/test_direct_acd_deliverables.py`, which has an unrelated user change already in the worktree.
- The separate Ignition report/diff implementation tracked by issue #24.

---

### Task 1: Build the pure naming engine and profile loader

**Files:**

- Create: `src/ignition_exporter/naming_engine.py`
- Create: `tests/ignition_exporter/test_naming_engine.py`
- Create: `tests/ignition_exporter/fixtures/kemco_style_corpus.json`

**Interfaces:**

```python
@dataclass(frozen=True)
class NamingProfile:
    display_root: str
    tokens: Mapping[str, str]
    phrases: tuple[tuple[str, str], ...]
    member_suffixes: Mapping[str, str | None]
    aliases: frozenset[str]
    test_markers: frozenset[str]
    explicit: Mapping[str, Mapping[str, str | None]]

@dataclass(frozen=True)
class Presentation:
    plc_tag: str
    name: str
    folder: str
    documentation: str
    tooltip: str
    is_test: bool
    unknown_tokens: tuple[str, ...]

def load_naming_profile(path: str | None = None) -> tuple[NamingProfile, str]: ...
def build_presentation(plc_tag: str, comment: str, profile: NamingProfile) -> Presentation: ...
def disambiguate_presentations(items: Sequence[Presentation]) -> list[Presentation]: ...
```

- [ ] **Step 1: Add failing unit tests for representative prototype behavior.** Cover
  `Program:MainProgram.Com_HWT1_LP_P2_Cmd_Hz`, member references such as
  `Com_HWT1.Temp`, alias names, alarm prefixes, test prefixes, `TOT_01.ACC`, and the
  folder routes `Boiler/Hot Water System/Low Pressure/Pump 2`, `Boiler/Diagnostics/Test`,
  and `Boiler/Flow Totalizers`.

  ```python
  def test_build_presentation_expands_phrase_and_routes_folder():
      profile, _ = load_naming_profile()
      result = build_presentation("Com_HWT1_LP_P2_Cmd_Hz", "", profile)
      assert result.name == "Hot Water Tank Low Pressure Pump 2 Command Speed"
      assert result.folder == "Boiler/Hot Water System/Low Pressure/Pump 2"
      assert result.tooltip == result.name
  ```

- [ ] **Step 2: Run the focused tests and verify they fail for the missing module.**

  Run:

  ```powershell
  .\venv\Scripts\python.exe -m pytest tests\ignition_exporter\test_naming_engine.py -q
  ```

  Expected result: collection fails because `ignition_exporter.naming_engine` does not yet exist.

- [ ] **Step 3: Port the deterministic prototype rules into the pure module.** Move the
  token and phrase dictionaries, member handling, scope stripping, alias recognition,
  alarm/test classification, name fallback, and folder precedence from
  `F:\Copia\Perry-Utilities\Kemco\PLC\work\gen.py`. Keep the profile immutable after
  loading. Normalize `Program:<scope>.` before naming, but preserve the original PLC ref
  in `Presentation.plc_tag`.

  Implement documentation as `comment.strip()` when a source comment exists, otherwise
  the generated friendly name. Set the tooltip to the generated name. Record unmapped
  tokens instead of dropping them.

- [ ] **Step 4: Add profile merge and validation tests before implementing the loader.**
  Test token replacement, phrase replacement, member suffix replacement, explicit
  per-tag name/folder overrides, display-root replacement, malformed JSON, wrong field
  types, and a missing profile path. A valid profile must merge over the built-in values;
  it must not erase unrelated built-in vocabulary.

  ```python
  def test_profile_extension_overrides_one_token(tmp_path):
      profile_path = tmp_path / "profile.json"
      profile_path.write_text(json.dumps({"tokens": {"HWT1": "Process Tank"}}), encoding="utf-8")
      profile, identity = load_naming_profile(str(profile_path))
      result = build_presentation("Com_HWT1_Temp", "", profile)
      assert result.name == "Process Tank Temperature"
      assert identity == str(profile_path.resolve())
  ```

- [ ] **Step 5: Implement `load_naming_profile` and the immutable profile merge.** Return
  `("built-in", profile)` when no path is supplied, and a normalized absolute profile
  identity for a supplied file. Raise `ValueError` with the field name for malformed
  profile content so the integration layer can return an actionable error before writing.

- [ ] **Step 6: Add deterministic collision tests and implementation.** Group by
  `(folder, name)`, append an alias qualifier where available, then append stable numeric
  suffixes in sorted PLC-reference order. Confirm the result is unique within each folder
  and that tooltip values follow the final disambiguated names.

- [ ] **Step 7: Add the 143-entry corpus fixture and regression test.** Copy the
  Kemco `style_corpus.json` entries as test data with no ACD/L5X content. Assert at least
  94% exact names and 98% exact folders, allowing the cleaner prototype mismatches to
  remain visible without requiring false exact matches.

- [ ] **Step 8: Run the completed engine test file and commit the self-contained unit.**

  Run:

  ```powershell
  .\venv\Scripts\python.exe -m pytest tests\ignition_exporter\test_naming_engine.py -q
  ```

  Expected result: all naming/profile/corpus tests pass.

  Commit:

  ```powershell
  git add src/ignition_exporter/naming_engine.py tests/ignition_exporter/test_naming_engine.py tests/ignition_exporter/fixtures/kemco_style_corpus.json
  git commit -m "Ignition: add deterministic naming engine"
  ```

---

### Task 2: Integrate human presentation into the exporter

**Files:**

- Modify: `src/ignition_exporter/ignition_mcp_integration.py:433-550`
- Modify: `tests/ignition_exporter/test_generate.py`
- Modify: `tests/ignition_exporter/test_overrides.py`

**Interfaces:**

```python
async def generate_ignition_tags(
    self,
    l5x_file_path: str,
    device_name: str,
    output_file_path: str,
    folder_hierarchy_model: str = "PhysicalSubsystem",
    enable_history_defaults: bool = True,
    target_tags: Optional[List[str]] = None,
    selection: str = "key_process_metrics",
    tag_overrides: Optional[List[Dict]] = None,
    naming: str = "raw",
    naming_profile_path: Optional[str] = None,
) -> Dict:
```

The existing `_ExportItem` collection and `_build_tag` technical arguments remain the
source of truth. Human mode creates an internal override map with the existing keys
`plc_tag`, `name`, `documentation`, `tooltip`, and relative `folder`.

- [ ] **Step 1: Add failing raw/human integration tests.** Extend `_generate` to pass
  optional naming arguments and add assertions that raw mode remains mechanically named,
  human mode uses the generated display root/folders, and the generated tag has the source
  comment or friendly-name documentation.

  ```python
  def test_human_mode_changes_presentation_not_technical_fields(synthetic_l5x, tmp_path):
      raw_dir = tmp_path / "raw"
      human_dir = tmp_path / "human"
      raw_dir.mkdir()
      human_dir.mkdir()
      raw_result, raw_out = _generate(synthetic_l5x, raw_dir, naming="raw")
      human_result, human_out = _generate(synthetic_l5x, human_dir, naming="human")
      raw = _load_tags(raw_out)[1]
      human = _load_tags(human_out)[1]
      assert {k: v["opcItemPath"] for k, v in raw.items()} == {k: v["opcItemPath"] for k, v in human.items()}
      assert raw_result["tags_written"] == human_result["tags_written"]
      assert human_result["naming_mode"] == "human"
      assert human_result["human_names_applied"] == human_result["tags_written"]
  ```

- [ ] **Step 2: Add failing tests for profile root, profile path, invalid configuration,
  and partial explicit overrides.** Confirm human mode can emit a profile-root folder
  without changing the OPC device prefix. Confirm `tag_overrides=[{"plc_tag": ...}]`
  keeps its exact selected set while the engine fills omitted presentation fields, and
  explicit `name`, `folder`, `documentation`, or `tooltip` values win field by field.
  Confirm an invalid `naming` or profile path returns `success=False` and leaves the
  output path absent.

- [ ] **Step 3: Run the new integration tests and verify they fail before wiring.**

  Run:

  ```powershell
  .\venv\Scripts\python.exe -m pytest tests\ignition_exporter\test_generate.py tests\ignition_exporter\test_overrides.py -q
  ```

  Expected result: the new tests fail because `generate_ignition_tags` does not accept
  `naming` or `naming_profile_path` and does not return naming metadata.

- [ ] **Step 4: Add profile loading and human override generation after technical item
  collection.** Validate `naming` before the baseline filename guard writes anything.
  Keep this precedence:

  ```text
  tag_overrides selection > target_tags > selection mode
  explicit override fields > profile explicit mapping > generated presentation > raw fallback
  ```

  In raw mode, execute the current branches unchanged. In human mode without explicit
  overrides, generate a presentation for every collected item, disambiguate the complete
  set, and route through `_override_tree`. In human mode with explicit overrides, collect
  only the explicit refs, generate missing fields, and retain supplied fields.

- [ ] **Step 5: Normalize profile folders and display root.** Treat the profile root as
  the output root and strip that leading component from each generated folder before
  passing the path to `_override_tree`. Use sanitized `device_name` as the root only when
  no profile display root exists. Never put the display root into `opcItemPath`.

- [ ] **Step 6: Add auditable result metadata and error handling.** Preserve all existing
  result keys and add `naming_mode`, `naming_profile`, `human_names_applied`,
  `naming_fallback_count`, and `naming_diagnostics`. Catch profile/mode `ValueError`s and
  return `{success: False, error: ...}` before output creation. Do not catch or suppress
  existing verification errors for synthetic or missing PLC refs.

- [ ] **Step 7: Run the exporter tests and commit the integration.**

  Run:

  ```powershell
  .\venv\Scripts\python.exe -m pytest tests\ignition_exporter -q
  ```

  Expected result: the original 48-test suite plus the new raw/human/profile tests pass.

  Commit:

  ```powershell
  git add src/ignition_exporter/ignition_mcp_integration.py tests/ignition_exporter/test_generate.py tests/ignition_exporter/test_overrides.py
  git commit -m "Ignition: integrate human naming into tag export"
  ```

---

### Task 3: Expose the naming options through MCP

**Files:**

- Modify: `src/mcp_server/studio5000_mcp_server.py:872-883,1650-1668,2101-2145`
- Modify: `tests/test_mcp_workaround_fixes.py`

**Interfaces:**

The MCP tool schema for `generate_ignition_tags` must add:

```python
"naming": {
    "type": "string",
    "enum": ["raw", "human"],
    "description": "Presentation naming mode; raw is the backward-compatible default."
},
"naming_profile_path": {
    "type": "string",
    "description": "Optional JSON profile extending the built-in deterministic naming rules."
}
```

Neither property is required.

- [ ] **Step 1: Add a failing MCP schema test.** Extend the existing `tools/list` test
  pattern in `tests/test_mcp_workaround_fixes.py`:

  ```python
  def test_generate_ignition_tags_schema_exposes_human_naming():
      server = Studio5000MCPServer(doc_root=".")
      response = asyncio.run(handle_mcp_request(
          server, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
      tool = next(t for t in response["result"]["tools"]
                  if t["name"] == "generate_ignition_tags")
      props = tool["inputSchema"]["properties"]
      assert props["naming"]["enum"] == ["raw", "human"]
      assert "naming_profile_path" in props
      assert "naming" not in tool["inputSchema"]["required"]
  ```

- [ ] **Step 2: Run the schema test and verify the new properties are absent.**

  Run:

  ```powershell
  .\venv\Scripts\python.exe -m pytest tests\test_mcp_workaround_fixes.py -q
  ```

  Expected result: the new schema assertion fails because the server surface has not
  been updated.

- [ ] **Step 3: Update the MCP registration description, handler signature, delegation,
  and schema.** Pass both optional values through without changing existing argument order
  or defaults. Describe human mode as deterministic presentation only, and retain the
  existing engineering-review warning.

- [ ] **Step 4: Run the MCP surface tests and commit the wiring.**

  Run:

  ```powershell
  .\venv\Scripts\python.exe -m pytest tests\test_mcp_workaround_fixes.py tests\ignition_exporter -q
  ```

  Expected result: schema, exporter, and existing workaround tests pass.

  Commit:

  ```powershell
  git add src/mcp_server/studio5000_mcp_server.py tests/test_mcp_workaround_fixes.py
  git commit -m "MCP: expose Ignition human naming options"
  ```

---

### Task 4: Run full verification and hand off

**Files:**

- Inspect only: all changed files and `docs/superpowers/specs/2026-08-10-human-ignition-naming-engine-design.md`

- [ ] **Step 1: Run the focused exporter and MCP suites from the repository venv.**

  ```powershell
  .\venv\Scripts\python.exe -m pytest tests\ignition_exporter tests\test_mcp_workaround_fixes.py -q
  ```

  Expected result: all focused tests pass, including the corpus thresholds and schema test.

- [ ] **Step 2: Run the complete pytest suite.**

  ```powershell
  .\venv\Scripts\python.exe -m pytest -q
  ```

  Expected result: no regressions. If the pre-existing ACD test modification affects a
  failure, report it separately and do not revert it.

- [ ] **Step 3: Run the documented MCP smoke test.**

  ```powershell
  .\venv\Scripts\python.exe src\mcp_server\studio5000_mcp_server.py --test
  ```

  Expected result: normal server startup, tool registration, and sample-query smoke path
  complete successfully with `generate_ignition_tags` still present.

- [ ] **Step 4: Review the final diff and worktree.**

  ```powershell
  git diff --check
  git status --short
  git log -4 --oneline --decorate
  ```

  Confirm only the intended implementation commits and the pre-existing modified test
  appear. Confirm no ACD/L5X/PDF, generated JSON, vector cache, or machine-specific
  profile artifact was added.

- [ ] **Step 5: Report the implementation handoff.** Include the commits, focused/full
  test results, MCP smoke result, profile usage example, and the remaining requirement for
  engineering review plus Ignition import validation. Do not close the GitHub issue or
  claim deployment readiness without explicit user direction and external validation.
