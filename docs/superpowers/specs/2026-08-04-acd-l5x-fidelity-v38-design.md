# ACD to L5X Fidelity for Studio 5000 v38

## Goal

Use the open-source `hutcheb/acd` parser as the default ACD analysis and L5X generation path, preserve all content the parser can recover, and report remaining parity gaps explicitly. The licensed Logix Designer SDK is disabled for this phase.

## Architecture

Pin `hutcheb/acd` commit `019fb7872e090f71fc11313b5b98ed468a92cc75` in the assistant environment and the repository conversion tasks. The local compatibility layer may patch confirmed parser defects, but it must not replace upstream serializers or builders when doing so discards upstream fields such as rung comments.

ACD analysis follows `ACD -> acd parser -> generated L5X -> existing L5X parser/index`. Conversion returns a semantic validation report so incomplete output is never described as lossless.

## Fidelity Contract

The generated file must parse as XML. Automated comparison against the matching native Studio export covers controller tags, programs, routines, rung text, rung comments, tag descriptions, operand comments, data types, AOIs, and modules. Differences are classified as matches, expected normalization, or losses.

The current toolchain targets Studio 5000 v38. The v31.02 import/re-export remains historical provenance for the original migration baseline, not the active compatibility target.

## SDK Boundary

ACD conversion and indexing must not import, initialize, probe, or call the Logix Designer SDK. Existing SDK documentation search code can remain dormant, but SDK-backed project operations are not registered as active MCP tools while this mode is disabled.

## Error Handling

Missing dependencies, malformed ACD content, invalid generated XML, and semantic losses return structured errors or warnings. A successful file write alone is not a successful high-fidelity conversion.

## Testing

Regression tests use the thaw-room ACD and its matching native L5X as the real integration fixture. Tests first prove the existing path drops rung comments, then verify preservation after the repair. Additional semantic tests cover rung logic and documentation-bearing elements. A final conversion records the complete parity report.
