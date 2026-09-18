# Design: Human-readable Ignition naming and folder engine

**Issue:** [FEAT-016 / #29](https://github.com/JLControls/studio5000-AI-Assistant/issues/29)

**Date:** 2026-08-10

**Status:** Approved for implementation

## Goal

Add an opt-in deterministic naming mode to `generate_ignition_tags` that turns PLC
references into operator-facing Ignition names, descriptions, tooltips, and process
folders. The mode must preserve the existing exporter's technical truth: OPC item paths,
data types, scaling, historian settings, selection, and exclusion behavior remain owned by
the MCP exporter.

Raw PLC naming remains the default so existing callers and generated manifests do not
change unless they explicitly request human naming.

## Existing context

The exporter currently builds technical `_ExportItem` objects from an L5X/ACD tag database
and accepts optional per-tag `tag_overrides` for human presentation. The Kemco engagement
proved the naming rules in `PLC/work/gen.py`, including token and phrase expansion, folder
routing, test/scratch classification, collision disambiguation, and a 143-tag style corpus
with approximately 94% exact name and 98% exact folder agreement.

The new engine will reuse those rules as a portable library. It will not copy the separate
Kemco merge pipeline or make the MCP depend on generated technical JSON files.

## Options considered

1. Port the prototype directly into `IgnitionMCPIntegration`. This is small initially but
   couples orchestration to project-specific naming rules and makes extension difficult.
2. Extract a pure naming engine with a profile boundary. This is the selected approach:
   it isolates presentation logic, supports deterministic unit tests, and permits project
   vocabulary extensions without changing technical export code.
3. Keep the prototype outside the MCP and require a manual override/merge step. This
   preserves current code but does not deliver the issue's requested workflow.

## Architecture

Add `src/ignition_exporter/naming_engine.py` containing no MCP, file-writing, or vector-DB
dependencies. Its public concepts are:

- `NamingProfile`: display root plus token, phrase, member, alias, explicit-name, and
  explicit-folder configuration.
- `Presentation`: generated name, folder path, documentation, tooltip, test marker, and
  diagnostic flags for one PLC reference.
- `load_naming_profile(path=None)`: load the built-in profile and optionally merge a JSON
  project profile over it.
- `build_presentation(plc_ref, comment, profile)`: produce one deterministic presentation.
- `disambiguate_presentations(items)`: guarantee unique names within each folder using the
  prototype's alias qualifier and stable numeric suffix rules.

The built-in profile ports the reusable Kemco vocabulary and routing rules. A project JSON
profile can extend or replace vocabulary and explicit mappings without changing Python. It
has this logical shape:

```json
{
  "display_root": "Boiler",
  "tokens": {"HWT1": "Hot Water Tank"},
  "phrases": [{"pattern": "Cmd_Hz", "replacement": "Command Speed"}],
  "member_suffixes": {"ACC": "Accumulator", "DN": null},
  "explicit": {
    "Some_Tag": {"name": "Operator Name", "folder": "Area/Equipment"}
  }
}
```

The profile is an extension point, not an LLM prompt. Unknown tokens remain visible in a
deterministic fallback name and are reported in diagnostics rather than silently discarded.

## Exporter integration

Extend both the integration method and MCP handler/schema with:

```text
naming: "raw" | "human" = "raw"
naming_profile_path: optional string = None
```

The request flow is:

1. Validate the naming mode and profile before creating the output file.
2. Collect `_ExportItem` objects using the existing selection precedence and technical
   rules.
3. If `naming="human"`, generate presentations for the selected items and disambiguate
   them in stable `(folder, plc_ref)` order.
4. Convert presentations into the existing override shape and pass them through the
   existing tag builder and arbitrary-depth folder tree.
5. Apply explicit `tag_overrides` fields last. Explicit overrides still define the exact
   selected set; in human mode, omitted presentation fields are filled by the naming
   engine. In raw mode, current override behavior is unchanged.
6. Verify the resulting tree against the L5X database and write the same technical JSON
   structure as today.

In human mode, a profile `display_root` becomes the output folder root when present; the
`device_name` remains unchanged in every OPC item path. Generated folder paths are relative
to that display root so the root is not duplicated. Without a profile root, the existing
sanitized `device_name` remains the root.

Human-mode descriptions use the source PLC comment when present and otherwise the generated
friendly name. Tooltips default to the final disambiguated friendly name. Human mode does
not invent process claims or alter scaling/historian metadata.

The result adds audit fields without removing existing fields:

- `naming_mode`
- `naming_profile` (built-in or normalized absolute profile identity)
- `human_names_applied`
- `naming_fallback_count`
- `naming_diagnostics`

Invalid modes or malformed profiles return the existing `{success: false, error}` shape and
must not create a partial output file.

## Testing

Add focused tests under `tests/ignition_exporter/`:

- Pure engine tests for scope/member normalization, phrase precedence, token expansion,
  folder routing, explicit mappings, unknown-token diagnostics, and collision handling.
- Profile-loading tests for built-in defaults, valid extensions, and malformed profiles.
- Integration tests proving raw mode remains unchanged and human mode changes only
  presentation fields.
- Technical parity assertions over identical raw/human exports for OPC paths, data types,
  scaling keys/values, historian keys, selected references, and exclusions.
- Explicit-override precedence tests, including partial overrides in human mode.
- A 143-tag style-corpus regression using the copied corpus from the Kemco engagement,
  asserting at least the prototype's 94% name and 98% folder match thresholds.

Run the existing Ignition suite and the full repository suite with the project Python 3.12
venv. The pre-existing modification to `tests/test_direct_acd_deliverables.py` is unrelated
and must not be overwritten.

## Non-goals and safety boundaries

- No changes to OPC binding, data typing, analog scaling, historian defaults, or tag
  selection semantics.
- No automatic inclusion of tags merely because human naming is enabled.
- No free-form model-generated names or descriptions.
- No implementation of the separate Ignition diff/report issue (#24).
- No claim that generated output is deployment-ready; engineering review and Ignition
  import validation remain required.

## Acceptance criteria

The issue is complete when:

1. `generate_ignition_tags` supports opt-in human naming through the MCP schema and direct
   integration API.
2. Raw mode is backward-compatible and existing tests pass.
3. Human mode produces deterministic names, descriptions, tooltips, folders, and collision-
   free nodes from the selected PLC references.
4. A project can extend the built-in profile without modifying production Python.
5. Technical fields are parity-tested between raw and human exports.
6. The 143-tag corpus meets or exceeds the prototype's 94%/98% regression thresholds.
7. Invalid configuration fails before output creation and reports an actionable error.

