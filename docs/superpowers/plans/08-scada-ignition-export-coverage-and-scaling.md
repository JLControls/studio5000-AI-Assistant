# SCADA Ignition Export Coverage, Scaling Fallback & Process Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Partial implementation. Raw analog alias retention is already present in the current exporter; the dated naming plan is canonical for Issue #29, while I/O coverage and reporting remain design work.

**Goal:** Complete the remaining SCADA export enhancements: verify isolated raw analog alias retention, implement the canonical deterministic naming engine, define physical-channel coverage, and emit a stable standalone HTML report.

**Architecture:**
1. **Raw Analog Alias Resolver (`tag_curation.py`, `ignition_mcp_integration.py`):** When raw analog alias tags (`Com_AliasAIn_*`) exist without corresponding scaled engineering tags (`_PV`), retain them under category `field_io` / unscaled analog point with clear documentation instead of pruning them.
2. **Deterministic Human Naming Engine (`naming_engine.py`):** Pure library that maps raw PLC abbreviations and scope prefixes into operator-facing display names, multi-tier process folders (`PhysicalSubsystem`), tooltips, and documentation while keeping technical fields (OPC item paths, scaling limits, data types) immutable.
3. **Physical Controller I/O Coverage Auditor (`io_coverage.py`):** Parses controller I/O hardware module definitions and channel configurations from L5X/ACD, cross-checks against exported SCADA tags, calculates coverage percentages, and identifies unmonitored sensors/actuators.
4. **Standalone HTML SCADA Visualizer & Diff Generator (`html_reporter.py`):** Zero-CDN, fully offline HTML dashboard providing category summaries, searchable/filterable tag tables, scaling ranges, and visual color-coded tag diffing against baseline exports.
5. **MCP Server Tool Surface (`studio5000_mcp_server.py`):** Exposes `audit_scada_io_coverage` and `generate_scada_export_report`, while adding `naming` and `naming_profile_path` parameters to `generate_ignition_tags`.

**Tech Stack:** Python 3.12, `xml.etree.ElementTree`, `dataclasses`, `pathlib`, `json`, `re`, HTML5/CSS3 (embedded, zero CDN), `pytest`, JSON-RPC MCP server.

---

## Global Constraints

- `naming="raw"` remains the default for `generate_ignition_tags` to preserve 100% backward compatibility.
- Technical fields remain owned by the MCP exporter: `opcItemPath`, `dataType`, `scaling`, `engUnit`, and historian configuration must never be modified by presentation naming.
- All naming rules, coverage audits, and HTML generation are strictly deterministic—no LLM, vector database, or external network requests are permitted.
- HTML reports must be completely self-contained (all styles, scripts, and SVG icons embedded inline) to function on air-gapped OT/SCADA workstations.
- Hardware module parsing must support ControlLogix 1756, CompactLogix 5069/1769, and POINT I/O 1734 channel addressing conventions without requiring external Rockwell EDS files.
- Generated PLC/SCADA configurations require professional engineering review and Studio 5000 / Ignition validation prior to deployment.

## Review gates before implementation

- Task 1 is a verification/closure task, not a fresh curation rewrite. Preserve the current raw-alias behavior and add regression coverage for the isolated/no-counterpart case.
- The naming engine was delivered by `../completed/2026-08-10-human-ignition-naming-engine.md` (merged to main 2026-09-18, `src/ignition_exporter/naming_engine.py`). Task 2 below is retained for reference only; do not re-implement it.
- I/O coverage must define a physical-channel denominator, not a tag denominator. Track unsupported/unknown module catalogs and address-normalization failures separately from unmonitored channels.
- Reports need a stable schema/version and consistent baseline field names. Escape arbitrary PLC comments/tag names for both embedded JSON and HTML; no raw string interpolation into scripts or markup.

---

## File Map

### Create:
- `src/ignition_exporter/naming_engine.py` — Pure deterministic process naming engine, vocabulary token/phrase tables, member suffix handler, and collision disambiguator.
- `src/ignition_exporter/io_coverage.py` — Controller hardware tree channel parser, SCADA tag cross-referencer, coverage percentage calculator, and spare I/O auditor.
- `src/ignition_exporter/html_reporter.py` — Self-contained HTML report and visual diff generator for Ignition tag exports.
- `tests/ignition_exporter/test_naming_engine.py` — Unit tests for token expansion, phrase mapping, collision resolution, and JSON profile extension.
- `tests/ignition_exporter/test_io_coverage.py` — Unit tests for hardware tree extraction and coverage calculation across diverse PLC module types.
- `tests/ignition_exporter/test_html_reporter.py` — Unit tests for HTML report rendering, diff generation, and standalone asset verification.
- `tests/ignition_exporter/test_scada_features.py` — End-to-end integration tests for raw alias retention, naming, I/O coverage, and HTML generation.
- `tests/ignition_exporter/fixtures/kemco_style_corpus.json` — 143-tag naming and folder regression corpus.

### Modify:
- `src/ignition_exporter/tag_curation.py` — Update `_collect_export_items`, `_is_raw_analog_alias`, `_scaled_counterpart_name`, and `is_export_relevant` for raw analog alias retention.
- `src/ignition_exporter/ignition_mcp_integration.py` — Wire `naming_engine`, expose `audit_scada_io_coverage`, `generate_scada_export_report`, and extend `generate_ignition_tags`.
- `src/mcp_server/studio5000_mcp_server.py` — Register new MCP tools (`audit_scada_io_coverage`, `generate_scada_export_report`), update `generate_ignition_tags` schema.
- `tests/ignition_exporter/test_curation.py` — Add tests for isolated raw alias retention vs. scaled counterpart pruning.
- `tests/ignition_exporter/test_generate.py` — Add tests for human naming mode, custom profiles, and diff generation.
- `tests/test_mcp_workaround_fixes.py` — Schema verification for new tools and parameters.

### Do Not Modify:
- `tests/test_direct_acd_deliverables.py` (preserve existing worktree changes).
- Core ACD Kaitai parsing definitions (`src/acd/generated/`).

---

## Task-by-Task Implementation Plan

### Task 1: Isolated Raw Analog Alias Retention & Curation Fallback (Issue #10)

**Files:**
- Modify: `src/ignition_exporter/tag_curation.py`
- Modify: `src/ignition_exporter/ignition_mcp_integration.py`
- Modify: `tests/ignition_exporter/test_curation.py`

**Interfaces:**
```python
def _scaled_counterpart_name(
    db: IgnitionTagDB,
    entry: TagEntry,
    scaling_points: List[Dict]
) -> Optional[str]:
    """Find an engineering-valued counterpart for a raw analog alias."""

def is_export_relevant(
    entry: TagEntry,
    write_map: Optional[TagWriteMap] = None
) -> bool:
    """Classify relevance; always preserve raw analog aliases lacking scaled counterparts."""
```

- [ ] **Step 1: Write failing unit test for isolated raw analog alias retention.**
  In `tests/ignition_exporter/test_curation.py`, add a test case where a PLC project has `Com_AliasAIn_HWT1_HtC1_Temp` (aliased to `Local:1:I.Ch0Data`) with NO downstream `_PV` or scaled REAL tag. Assert that `candidate_inventory()` and `_collect_export_items()` retain this tag under category `field_io` with `recommended=True` and `advisory="unscaled_analog_point"`.

  ```python
  def test_isolated_raw_analog_alias_retained_when_no_pv_exists(synthetic_l5x_tag_db):
      # Create DB containing raw alias but no corresponding engineering PV
      db = synthetic_l5x_tag_db
      entry = db.get("Com_AliasAIn_Isolated_Temp")
      assert entry is not None
      scaling_points = []  # No SCP/SCL scaling detected
      items, excluded = _collect_export_items(db, scaling_points, prune_scaled_raw_aliases=True)
      item_refs = [i.plc_ref for i in items]
      assert "Com_AliasAIn_Isolated_Temp" in item_refs
      item = next(i for i in items if i.plc_ref == "Com_AliasAIn_Isolated_Temp")
      assert item.advisory == "unscaled_analog_point"
  ```

- [ ] **Step 2: Run test to confirm failure.**
  ```bash
  python -m pytest tests/ignition_exporter/test_curation.py -k "test_isolated_raw_analog_alias" -v
  ```

- [ ] **Step 3: Update `_scaled_counterpart_name` and curation logic.**
  In `src/ignition_exporter/tag_curation.py` and `src/ignition_exporter/ignition_mcp_integration.py`:
  - Enhance `_scaled_counterpart_name()` to verify if an engineering counterpart actually exists in the project tag database or scaling instruction maps.
  - When `prune_scaled_raw_aliases=True`, only prune `Com_AliasAIn_*` if `counterpart is not None` AND counterpart is included in selection.
  - If counterpart is `None`, set `advisory="unscaled_analog_point"` and populate tag documentation parameter: `"note": "Unscaled raw analog field channel"`.

- [ ] **Step 4: Verify test passes.**
  ```bash
  python -m pytest tests/ignition_exporter/test_curation.py -v
  ```

---

### Task 2: Deterministic Human-Readable Process Naming Engine (Issue #29)

**Files:**
- Create: `src/ignition_exporter/naming_engine.py`
- Create: `tests/ignition_exporter/test_naming_engine.py`
- Create: `tests/ignition_exporter/fixtures/kemco_style_corpus.json`
- Modify: `src/ignition_exporter/ignition_mcp_integration.py`
- Modify: `tests/ignition_exporter/test_generate.py`

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

- [ ] **Step 1: Create failing unit tests for naming engine.**
  In `tests/ignition_exporter/test_naming_engine.py`:
  - Test token expansions: `Htr` -> `Heater`, `Disch` -> `Discharge`, `P1` -> `Pump 1`, `Tnk` -> `Tank`, `Vlv` -> `Valve`, `Temp` -> `Temperature`.
  - Test multi-token phrase resolution: `HtC` -> `Heating Circuit`, `HWT` -> `Hot Water Tank`, `LP` -> `Low Pressure`.
  - Test member suffixes: `.ACC` -> `Accumulator`, `.PRE` -> `Preset`, `.DN` -> `Done`.
  - Test folder hierarchy pathing: `HWT1_HtC1_Temp_PV` -> Folder: `Hot Water Tank 1 / Heating Circuit 1`, Tag Name: `Temperature`.
  - Test profile inheritance and JSON override loading.
  - Test collision disambiguation for identically named tags within the same folder.

- [ ] **Step 2: Run naming engine tests to confirm missing module failure.**
  ```bash
  python -m pytest tests/ignition_exporter/test_naming_engine.py -v
  ```

- [ ] **Step 3: Implement `src/ignition_exporter/naming_engine.py`.**
  - Implement built-in standard vocabulary dictionary and deterministic regex tokenizer.
  - Implement `load_naming_profile()` supporting optional user JSON profile extension.
  - Implement `build_presentation()` creating human-friendly names, descriptions, tooltips, and folder routes.
  - Implement `disambiguate_presentations()` ensuring unique tag names per folder with deterministic numerical or alias suffixes.

- [ ] **Step 4: Load 143-tag regression corpus fixture and verify accuracy.**
  Create `tests/ignition_exporter/fixtures/kemco_style_corpus.json` with 143 representative tags. Assert $\ge 94\%$ name accuracy and $\ge 98\%$ folder accuracy.

- [ ] **Step 5: Integrate naming engine into `generate_ignition_tags`.**
  In `src/ignition_exporter/ignition_mcp_integration.py`:
  - Add `naming: str = "raw"` and `naming_profile_path: Optional[str] = None` parameters.
  - When `naming == "human"`, run `build_presentation()` and `disambiguate_presentations()` to populate display names and folders while keeping `opcItemPath` and technical properties strictly unchanged.

- [ ] **Step 6: Run tests and verify.**
  ```bash
  python -m pytest tests/ignition_exporter/test_naming_engine.py tests/ignition_exporter/test_generate.py -v
  ```

---

### Task 3: Physical Controller I/O Coverage Audit Tool (Issue #25)

**Files:**
- Create: `src/ignition_exporter/io_coverage.py`
- Create: `tests/ignition_exporter/test_io_coverage.py`
- Modify: `src/ignition_exporter/ignition_mcp_integration.py`
- Modify: `src/mcp_server/studio5000_mcp_server.py`

**Interfaces:**
```python
@dataclass
class PhysicalChannel:
    module_name: str
    catalog_number: str
    slot: Optional[int]
    channel_id: str
    channel_type: str  # 'DI', 'DO', 'AI', 'AO'
    raw_tag_address: str
    alias_tag_name: Optional[str] = None
    description: str = ""

@dataclass
class IOCoverageResult:
    total_physical_channels: int
    covered_channels: int
    unmonitored_channels: int
    coverage_percentage: float
    channel_details: List[Dict[str, Any]]
    unmonitored_channel_list: List[Dict[str, Any]]

def audit_controller_io_coverage(
    l5x_file_path: str,
    ignition_tags_json_path: str
) -> IOCoverageResult: ...
```

- [ ] **Step 1: Write failing unit test for I/O coverage calculation.**
  In `tests/ignition_exporter/test_io_coverage.py`, construct a synthetic L5X with 1756-IB16 (16 DI), 1756-OB16 (16 DO), and 1756-IF8 (8 AI) modules:
  - Generate an Ignition tags JSON containing 24 of the 40 channels.
  - Assert `total_physical_channels == 40`, `covered_channels == 24`, `unmonitored_channels == 16`, `coverage_percentage == 60.0`.
  - Assert unmonitored channels correctly identify module name, slot, channel ID, and raw address.

- [ ] **Step 2: Run test to confirm failure.**
  ```bash
  python -m pytest tests/ignition_exporter/test_io_coverage.py -v
  ```

- [ ] **Step 3: Implement `src/ignition_exporter/io_coverage.py`.**
  - Parse `<Modules>` and `<Module>` XML nodes from L5X.
  - Extract physical I/O data channels for Rockwell digital and analog modules (1756, 5069, 1769, 1734 families).
  - Map PLC aliases linking controller tags to physical channel structures (`Local:1:I.Ch0Data`, `Local:2:O.Data.4`, etc.).
  - Cross-reference physical addresses against Ignition `opcItemPath` and tag references in `tags.json`.
  - Return structured `IOCoverageResult` with full breakdown of covered and unmonitored field points.

- [ ] **Step 4: Expose `audit_scada_io_coverage` in `IgnitionMCPIntegration`.**
  Add async method `audit_scada_io_coverage(l5x_file_path, ignition_json_file_path)` in `src/ignition_exporter/ignition_mcp_integration.py`.

- [ ] **Step 5: Run tests and verify.**
  ```bash
  python -m pytest tests/ignition_exporter/test_io_coverage.py -v
  ```

---

### Task 4: Standalone HTML SCADA Export Visualization & Diff Generator (Issue #24)

**Files:**
- Create: `src/ignition_exporter/html_reporter.py`
- Create: `tests/ignition_exporter/test_html_reporter.py`
- Modify: `src/ignition_exporter/ignition_mcp_integration.py`
- Modify: `src/mcp_server/studio5000_mcp_server.py`

**Interfaces:**
```python
def generate_html_export_report(
    ignition_tags_json_path: str,
    output_html_path: str,
    baseline_tags_json_path: Optional[str] = None,
    io_coverage: Optional[IOCoverageResult] = None,
    project_title: str = "Ignition SCADA Tag Export Report"
) -> str:
    """Generate a self-contained HTML dashboard and diff visualization."""
```

- [ ] **Step 1: Write failing unit test for HTML dashboard generation.**
  In `tests/ignition_exporter/test_html_reporter.py`:
  - Test report generation without baseline (summary cards, category breakdowns, interactive search table).
  - Test report generation with baseline diff (highlight added tags in green, modified in yellow, deleted in red).
  - Assert output file contains NO external CDN links (no `http://`, `https://` in `<script src=...>` or `<link href=...>`).
  - Verify embedded CSS and JavaScript render properly in headless browser or string verification.

- [ ] **Step 2: Run test to confirm failure.**
  ```bash
  python -m pytest tests/ignition_exporter/test_html_reporter.py -v
  ```

- [ ] **Step 3: Implement `src/ignition_exporter/html_reporter.py`.**
  - Implement standalone HTML template with modern dark/light responsive CSS.
  - Implement summary metric widgets: Total Tags, Analog Scaled, Field I/O, Alarms, Commands, I/O Coverage %.
  - Implement category filtering buttons and instant client-side search across tag names, OPC paths, and engineering units.
  - Implement side-by-side or unified diff renderer when baseline JSON is provided.
  - Write output directly to `output_html_path`.

- [ ] **Step 4: Expose `generate_scada_export_report` in `IgnitionMCPIntegration`.**
  Add async method `generate_scada_export_report(...)` in `src/ignition_exporter/ignition_mcp_integration.py`.

- [ ] **Step 5: Run tests and verify.**
  ```bash
  python -m pytest tests/ignition_exporter/test_html_reporter.py -v
  ```

---

### Task 5: Expose New Tools and Arguments through MCP Server

**Files:**
- Modify: `src/mcp_server/studio5000_mcp_server.py`
- Modify: `tests/test_mcp_workaround_fixes.py`

- [ ] **Step 1: Write failing schema tests in `tests/test_mcp_workaround_fixes.py`.**
  Assert `tools/list` returns:
  - `audit_scada_io_coverage` tool with required `l5x_file_path` and `ignition_json_file_path`.
  - `generate_scada_export_report` tool with `ignition_json_file_path`, `output_html_path`, and optional `baseline_json_file_path`.
  - `generate_ignition_tags` tool contains `naming` (enum: `["raw", "human"]`) and `naming_profile_path` properties.

- [ ] **Step 2: Run schema test to confirm failure.**
  ```bash
  python -m pytest tests/test_mcp_workaround_fixes.py -k "ignition" -v
  ```

- [ ] **Step 3: Update `studio5000_mcp_server.py`.**
  - Register `audit_scada_io_coverage` in `_register_tools()` and implement delegator method.
  - Register `generate_scada_export_report` in `_register_tools()` and implement delegator method.
  - Update `generate_ignition_tags` tool registration, delegator, and inputSchema in `tools/list`.

- [ ] **Step 4: Verify schema and MCP tests.**
  ```bash
  python -m pytest tests/test_mcp_workaround_fixes.py -v
  ```

---

### Task 6: Full End-to-End Verification & Regression Testing

**Files:**
- Create: `tests/ignition_exporter/test_scada_features.py`

- [ ] **Step 1: Run complete ignition exporter test suite.**
  ```bash
  python -m pytest tests/ignition_exporter/ -v
  ```
  Expected: All unit, curation, naming, coverage, reporter, and integration tests pass.

- [ ] **Step 2: Run MCP server smoke test.**
  ```bash
  python src/mcp_server/studio5000_mcp_server.py --test
  ```
  Expected: Server starts cleanly, tools register properly, sample queries pass.

- [ ] **Step 3: Verify git status.**
  Ensure no temporary files or unwanted artifacts were created.

---

## Verification Commands

```bash
# 1. Run all Ignition exporter tests
python -m pytest tests/ignition_exporter -v

# 2. Run MCP server smoke test
python src/mcp_server/studio5000_mcp_server.py --test

# 3. Run full test suite
python -m pytest -q
```
