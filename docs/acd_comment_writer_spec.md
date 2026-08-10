# Spec: Direct ACD Comment Writer (`patch_comments`)

**Status:** Not started — design/spec only. Tracked as FEAT-009 (GitHub issue #22) / BUG-006 (issue #6).

**Goal:** Write tag/operand comment *descriptions* directly into an `.ACD` file's
`Comments.Dat`, so `analyze_comment_graph` / `generate_comment_deliverables` with
`edit_acd=True` can emit a modified ACD that already contains the documentation —
not only the `Comment_Delta.CSV` import.

## Why this is needed

Today `edit_acd` only calls `patch_rungs` (rung **text** via `SbRegion.Dat`). There is
**no** comment writer, so:
- `acd/record/comments.py` only *parses* comments (`CommentsRecord.parse`).
- `pipeline.generate_deliverables(edit_acd=True)` with comment-only decisions produces
  an ACD with **zero** changes (empty `changes` dict → project re-saved unchanged).

The vendor-sanctioned path (and current recommended deliverable) is the
`Comment_Delta.CSV` import in Studio 5000, which generates correct internal bindings.
This feature reproduces that binding offline.

## Current working foundation (reuse these)

- **Container write** is solved and cheap: `acd/zip/unzip.py` `Unzip` → mutate
  `_raw_files["Comments.Dat"]` → `acd/zip/write_acd.py` `build_acd_bytes(files, file_order, footer_unknown)`.
  Container offsets are recomputed automatically, so changing `Comments.Dat` length is safe.
  **Do not** route through `ExportL5x`/`load_acd` for writing — that builds the full object
  model and takes minutes; the raw-container path is seconds.
- **Precedent:** `acd/zip/write_dat.py` `patch_sbregion_dat` already rebuilds a `.Dat`
  record stream (walk records, replace, recompute header `file_length` + `number_records_fafa`,
  preserve trailer verbatim). `patch_comments` mirrors this exactly.
- `save_acd` needs a registered FileInfo key only when the SDK must accept the file; for
  offline round-trips it writes as-is (see `acd/api.py:save_acd`).

## Comments.Dat format (verified on ModernTHAWROOM021722.ACD)

DAT container header (offset 0), identical to `SbRegion.Dat` / `acd/generated/dat.py::Header`:

| off | field | notes |
|----|-------|-------|
| 0  | format_type u32 | |
| 4  | blank_2 u32 | |
| 8  | file_length u32 | **bounds records region**; records = `[first_record_position : file_length+1]` |
| 12 | first_record_position u32 | e.g. 8192 |
| 16 | blank_3 u32 | |
| 20 | number_records_fafa u32 | count of 0xFAFA records — must be updated |
| 24 | header_buffer | `first_record_position - 24` bytes, copy verbatim |

Records region: sequence of `[identifier u16][len_record u32][payload (len_record-6)]`.
`identifier` ∈ {0xFAFA=64250 (comment), 0xFDFD, 0xFEFE, 0xBFFB}. Reader (`Dat.Records`)
walks **linearly** to EOF of the records substream. Trailer after `file_length+1` is
copied verbatim (`patch_sbregion_dat` does this and Studio accepts it, which implies Studio
re-walks records rather than trusting absolute-offset indices — the key reason appends are viable).

### FafaComents payload (`acd/generated/comments/fafa_coments.py`)

`payload` = `record_length u32` (=10+len(body)) + 10-byte header + body.
Header: `seq_number u16 @0`, `record_type u16 @2`, `sub_record_length u16 @4`, `parent u32 @6`.

Observed `record_type` histogram (2247 FAFA records): `{1:1928, 4:17, 5:111, 6:28, 7:32, 8:9, 11:80, 21:32}`.

Two families matter for writing:

1. **Type 1 (AsciiRecord) — tag/component descriptions.** Body:
   `unknown_1[13]`, `object_id u32`, `unknown_2[13]`, `record_string UTF-8 (null-term)`.
   `unknown_1[0:4]` = member_ref (0 for object-level), `unknown_1[4:8]` = rung_content flag.
   Binds by **object_id alone** → resolvable via `Comps` (`object_id ↔ comp_name`).
   **Lower risk.** Do this first.

2. **Type 11 (and 3–8 variants) — operand/member comments.** Body carries an internal
   **operand reference** like `.!0625AD82` (a hex object handle), *not* the readable path.
   Example: `Glycol Pump 1\r\nRun Command` stored with tag_reference `.!0625AD82`.
   Reproducing this handle = reproducing Studio's operand-reference encoding (derive from
   `Comps`/`XRefs` object graph). **Higher risk.** Do this second, template-cloned.

## Phased plan

1. **Round-trip test (safety net).** `Unzip` → `build_acd_bytes` with unmodified
   `_raw_files` must be byte-identical to source. Add as a pytest over a fixture ACD.
2. **`patch_comments_dat(dat_bytes, changes)`** in `acd/zip/write_dat.py`, mirroring
   `patch_sbregion_dat`: decompress, parse header, walk records, **modify** existing comment
   records' text, recompute `file_length`/`number_records_fafa`, preserve trailer. Validate by
   re-parsing with `CommentsRecord`.
3. **Append new type-1 records** for tag-level descriptions. Resolve `object_id` from `Comps`;
   clone an existing type-1 record as a template and swap `object_id` + UTF-8 text + fix length
   fields. Validate via re-parse + ACD→L5X conversion showing the new `<Description>`.
4. **Append type-11 operand records.** Derive the internal operand handle from the object graph;
   template-clone a real type-11 record. This is the hard part — needs Studio validation.
5. **Wire into pipeline.** `acd/api.py::patch_comments(project, changes)` + call it from
   `comment_pipeline.generate_deliverables` when decisions carry descriptions (not just
   `PROPOSED_RUNG_TEXT`). Split decisions into tag-level (type 1) vs operand (type 11) by
   presence of `SPECIFIER`/member path.

## Validation gap (must read)

No Studio 5000 / Logix Designer SDK runs in this environment (`STUDIO5000_SDK_ENABLED=false`).
Offline we can only validate by (a) re-parsing the rewritten `Comments.Dat` and (b) ACD→L5X
conversion showing the comments. **Final acceptance requires opening the modified ACD in
Studio 5000.** Do not ship the type-11 path as trusted until a human confirms a Studio open +
comment display on a real project. Recommended: gate the writer behind an explicit flag and
keep CSV import as the default until validated.

## Repro / investigation scripts

Fast offline extraction + record decoding used to derive the above live in the session
scratchpad (not committed): `fast_extract.py`, `decode_records.py`, `decode_type1.py`.
They pull `Comments.Dat`/`Comps.Dat` via `Unzip` (seconds) and dump record templates by type.
