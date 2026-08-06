---
name: ignition-tag-export
description: Use when working on the Studio 5000 to Ignition SCADA tag export (src/ignition_exporter) — generating an Ignition tag import JSON from an L5X/ACD project, analog scaling detection, OPC path auditing, historian config, or curating which PLC tags to import. Covers the ACD-zeroes-values trap and the correct Ignition scaling keys.
---

# Ignition Tag Export (src/ignition_exporter)

## Overview

`src/ignition_exporter/` turns a Studio 5000 project into an Ignition v8.1+ JSON tag
import. The engine is `IgnitionMCPIntegration` (pure/offline — no vector DB). It backs
seven MCP tools. Domain logic is in per-file modules; the MCP server file just delegates.

## The three traps that will bite you

1. **The offline ACD→L5X converter ZEROES every tag data-table value.** A converted
   `.L5X` (via `convert_acd_to_l5x` / the vendored `src/acd`) has all `DataValue`/
   `DataValueMember` = 0 — so scaling members (`InputMin/InputMax/ScaledMin/ScaledMax`)
   and setpoint values come back as zeros and scaling can't resolve. A **native Studio
   5000 L5X export preserves the values**. Rule: for anything that reads real *values*
   (scaling, setpoints), require a native export; only structure survives conversion.
   Root cause + fix plan: ROADMAP FEAT-010 (`src/acd/l5x/elements.py` emits zeros;
   `_data_table_instance` parsed but never dereferenced).

2. **Ignition scaling keys (confirmed vs Inductive Automation docs):** the value
   conversion is `scaleMode="Linear"` + `rawLow`/`rawHigh` → **`scaledLow`/`scaledHigh`**.
   `engLow`/`engHigh`/`engUnit` are a SEPARATE display/deadband concept, NOT the
   conversion. An older reference conflated them (used engLow/engHigh as the scaled
   output) — that is wrong. Keys are centralized in `ignition_tag_builder.py`.

3. **Never write value deadbands.** The builder writes only `historyEnabled`,
   `historyProvider`, `historyMaxAge`, `historyTimeDeadband`. Never
   `historicalDeadband`/`historicalDeadbandMode`/`deadband`. `suggest_historian_config`
   may *report* an advisory value deadband, but it is never written into a tag. Historian
   defaults come from `historian_rules.py` by signal type (continuous PV → enabled,
   `historyTimeDeadband` 10-30s; discrete alarm/status → 0s on-change; static → off).

## Tag JSON shape

The builder DOES write `engLow`/`engHigh`/`engUnit` (display/deadband metadata) — the
"separate concern" in trap #2 means they are not the *conversion*, not that they are
omitted. In the real file, `=` and `&` inside `opcItemPath` are serialized as their
unicode escapes (`u003d`/`u0026`, each prefixed by a backslash) and JSON keys are sorted;
the examples below show `opcItemPath` unescaped for readability.

```json
// Ignition converts raw hardware -> engineering (raw-fallback):
{ "name": "Turbidity", "dataType": "Int2", "valueSource": "opc",
  "opcItemPath": "ns=1;s=[Device]AIn_Turbidity_Raw",
  "scaleMode": "Linear", "rawLow": 0.0, "rawHigh": 4095.0,
  "scaledLow": 0.0, "scaledHigh": 100.0,        // <- the real conversion
  "engLow": 0.0, "engHigh": 100.0, "engUnit": "NTU" }   // <- display only

// Tag is already engineering (PLC scaled it) -> NO scaleMode/raw/scaled, eng only:
{ "name": "Header Pressure", "dataType": "Float4", "valueSource": "opc",
  "opcItemPath": "ns=1;s=[Device]Com_CW_Hdr_Pres",
  "engLow": 0.0, "engHigh": 100.0, "engUnit": "PSI",
  "historyEnabled": true, "historyProvider": "Ignition_SCADA",
  "historyMaxAge": 24, "historyTimeDeadband": 10 }
```

## The seven tools

| Tool | Module | Purpose |
|------|--------|---------|
| `list_ignition_tag_candidates` | `tag_curation.py` | Categorized inventory + `recommended` flag — the curation dialog's first step |
| `generate_ignition_tags` | `ignition_mcp_integration.py` | Build/write the Ignition JSON |
| `extract_analog_scaling` | `analog_scaling.py` | Signal-flow-aware scaling per point |
| `audit_opc_item_paths` | `opc_audit.py` | Case-sensitive OPC-path audit vs L5X |
| `suggest_historian_config` | `historian_rules.py` | Historian rec by signal type |
| `propose_folder_structures` | `folder_structures.py` | Candidate folder trees |
| `sanitize_ignition_nodes` | `ignition_tag_builder.py` | Node-name cleaning preview |

Shared loader: `l5x_tags.py` (`load_tag_db` → `IgnitionTagDB`; reuses
`PLCCommentPipeline.resolve_l5x_path`/`parse_l5x_tree`; adds `ExternalAccess`, decorated
member values, atomic scalar `value`, and a rung index).

## Curation is a dialog — do NOT dump every tag

A generalized L5X has ~1000+ addressable tags (comms structs, configurators, AOI
internals). Dumping them all is the failure mode. Correct flow for a "key process
metrics"-style request:

1. Call `list_ignition_tag_candidates` → review categories (`analog_pv`, `setpoint`,
   `alarm`, `status`, `command`, `field_io` vs noise: `comms`, `config`, `internal`).
2. Make judgement calls on what matters; **ask the user when unsure**. Category alone is
   too coarse (e.g. `command` includes Auto/En/Jog HMI bits, not just `_Cmd_Hz` speeds) —
   refine within categories by name.
3. Call `generate_ignition_tags(target_tags=<your curated list>)`.

`generate_ignition_tags` defaults to `selection="key_process_metrics"` (operator-facing
tags), NOT a dump; `selection="all"` is the opt-in escape hatch. **Precedence:** an
explicit `target_tags` list wins entirely — `selection` is ignored when `target_tags` is
given. Single-tag folders are merged into a `System` folder so the tree reads as real
process areas.

## Analog scaling: which member is the engineering value

`extract_analog_scaling` reasons about signal direction:
- **Analog input** (mA/counts → process): expose the block's **`.Output`**; eng range =
  `[ScaledMin, ScaledMax]`.
- **Analog output** (Hz command → counts): expose the tag feeding **`.Input`**; eng range
  = `[InputMin, InputMax]`.
- **Raw-hardware fallback** (no OPC-addressable engineering tag): expose raw, Ignition
  converts `rawLow/rawHigh → scaledLow/scaledHigh`.
- **Process transmitter with no SCP block:** a raw alias-AI + a companion `_Sc`
  scale-setpoint (its *value* is the engineering full-scale) + an engineering PV, matched
  by shared name stem → expose the PV with `eng=[0, setpoint value]`.
- **Distrust all-zero / partial / identity ranges** → flag `scaling_source="none_found"`;
  never emit `[0,0]` or a raw==scaled identity. Never assume standard raw ranges (a real
  block may be `0-10000` counts, not `0-16384`).

## Dev conventions

- Run on **Python 3.12** (`venv/Scripts/python.exe`), not the shell's 3.14. Bare imports
  (`from ignition_exporter... import`), never `from src...`.
- Tests: `venv/Scripts/python.exe -m pytest tests/ignition_exporter/ -p no:cacheprovider`.
  Also run `tests/acd/` and the MCP smoke test (`studio5000_mcp_server.py --test`).
- Committed tests use the **hand-authored `tests/ignition_exporter/fixtures/
  synthetic_ignition.L5X`** — never proprietary project files. `*.L5X` is gitignored, so
  that fixture is kept tracked by an explicit `!`-negation in `.gitignore`; a new L5X
  fixture needs the same.
- Guardrail: `generate_ignition_tags` refuses to write `ignitionTags.json` (read-only
  baseline). Generated SCADA output requires engineering review before deployment.
- Category rules use common Rockwell naming *conventions* (Alias/Set/Comms/Cnfg/`_Sc`),
  never project-specific tag names.

## Server wiring (adding a tool)

Five edits in `src/mcp_server/studio5000_mcp_server.py`: import; `__init__`
(`_ignition_integration=None` + `'ignition'` lock); lazy `@property ignition_integration`;
an `add_tool(...)` call; an `async def` handler; and an `elif name==...` schema block in
the `tools/list` chain. Handler params must match the schema property names exactly.
