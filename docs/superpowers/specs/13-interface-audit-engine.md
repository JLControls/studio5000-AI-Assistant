# Interface Audit Engine — spec

Status: proposed (revised 2026-09-17 after the adversarial audit and the unloader pass).
Relocated from `plans/` on 2026-09-18: this is a proposal without checkbox tasks. Before a
plan is written, §2 must be rewritten against `src/l5x_analyzer/tag_cross_reference.py` and
`l5x_fact_accessor.py`, which already cover much of §4.2 and §4.1g. See `../ROADMAP.md` Phase 6.
Date: 2026-09-17
Motivating job: audit `PLC_IsolaCaricoSalami1.l5x` (Perry-Stuffing Line 1, Rack Loading / Vemac)
against the vendor's `LoadingVariablesList.xlsx` MES interface document. A second pass audited
the first agent's output and then repeated the job on the Line 1 unloader
(`Perry-PrimaryPack/Line1Combo/Unloader-Vemac/plc/PLC_IsolaScaricoSalami.L5X`). Both passes
are folded in below; where the first agent's conclusions were wrong, the spec now carries
the verified fact and the test that would have caught the error.

Private source files for local audit and integration validation:

- Loader: `F:\Copia\Perry-Stuffing\Line1\RackLoading-Vemac\plc\PLC_IsolaCaricoSalami1.l5x`
- Unloader: `F:\Copia\Perry-PrimaryPack\Line1Combo\Unloader-Vemac\plc\PLC_IsolaScaricoSalami.L5X`

These are local input locations, not portable defaults or repository fixtures. Keep the
proprietary files outside the repository; see §6 for public fixture requirements.

**Revision summary.** The first draft baked three false findings into its acceptance
criteria (§4.3) and left the COP semantics open (§7). Those are now resolved from Rockwell's
reference and from 30 days of historian data. The draft also lacked the checks that produced
most of the real defects: source-has-no-writer, MSG destination/type mismatches, INT counter
wrap, ONS bit reuse, and rung-comment-versus-tag-comment conflicts. It had no UDT byte-layout
model, without which "overrun into the next member" cannot be computed.

## 1. Why

An agent was asked to check a vendor MES interface spreadsheet against the PLC that
implements it. It produced five real findings, including one High-severity defect
(44 alarm bits never reach the MES because two `COP` instructions overlap).

**It used zero tools from this MCP server.** Every finding came from `grep -o` and a
hand-written Python regex pass over the raw 2 MB L5X. That is the problem this spec
addresses. The server has 54 tools and none of them answered the three questions the
job actually consisted of:

1. What writes this tag — down to the individual bit?
2. Does any data-movement instruction overrun its source or destination?
3. Where does this external tag list disagree with the code?

The work took ~10 shell round-trips and a bespoke 300-line script. With the tools below
it is three calls and no script.

### Cost breakdown of the manual approach

| Step | How it was done | Cost |
|---|---|---|
| Find writers of `MES.LineState.*` | `grep -o` for the literal string | 1 call, but **unsound** (see §2.1) |
| Attribute rungs to a routine | `sed -n` a line window, scan backwards for `<Routine>` | 2 calls, guesswork |
| Get UDT member types/dimensions | ad-hoc `re.search` with a hand-built non-greedy `DataType` pattern | 1 call |
| Spot the `COP` overlap | noticed by eye while reading the dimensions | **luck** |
| Extract alarm comments with correct tag attribution | custom `<Tag>`-block walker | 2 calls |
| Reconcile against the xlsx | openpyxl by hand | 1 call |
| Emit the corrected workbook | 300-line bespoke openpyxl script | 1 large write + 1 run |

The two weakest links are the ones marked unsound and luck. Both are mechanically
checkable and neither should depend on the agent's attention.

## 2. Root causes in the current codebase

### 2.1 `write_analyzer.py` exists but is invisible and incomplete

`src/l5x_analyzer/write_analyzer.py` (151 lines) already walks every `Routine`/`Rung`,
already resolves AOI output parameters by index, and already records
`{tag: [routine:Rung]}` locations. It is the right engine. Three problems:

- **Not exposed.** It is only reachable through the Ignition/SCADA export path, used as a
  boolean filter (`is_written`) to drop unwritten tags from export candidates. No MCP
  tool and no CLI surfaces it.
- **Blind to `COP`.** `DESTRUCTIVE_DEST_RE` covers `MOV|MVM|CPT|ADD|SUB|MUL|DIV|CLR|FLL|SWPB`.
  `COP` and `CPS` are absent. In the motivating job, `COP` is how *every* alarm word, drive
  speed and robot position reaches the MES — the entire interface was invisible to this
  engine, and all three data-movement defects live in `COP` instructions.
  (`tag_analyzer/comment_pipeline.py:542` has a separate hardcoded list that *does*
  include `COP` — two divergent notions of "output instruction" in one repo.)
- **Site-specific naming hardcoded.** `Com_AliasDIn_`, `Htr1_Cmd_`, `Set_`, `Cmd_` prefixes
  are baked into `analyze_l5x_tag_writes`. These are from a different customer's naming
  convention and silently misclassify on Vemac/Colussi projects.

Note in its favour: `_clean_tag_ref` strips array indices but the write set stores **both**
the full and the cleaned reference, so `is_written("MES.LineState.12") -> False` is already
correct. Bit-level resolution is achievable without redesign.

### 2.2 `search_l5x_content` returns XML, not logic

Callers get `<![CDATA[...]]>` with `&#10;` entities and no enclosing-routine context, so
every consumer re-implements the same strip/decode/backscan. Rung→routine attribution was
done by `sed`-ing a line range and reading backwards.

### 2.3 Comment operands are returned unqualified

Alarm comments are stored as `Operand=".ALLARMI_ZONA[0].0"` inside a `<Tag>` block.
`Dati_Zona_Carico` and `Dati_Zona_Ribaltatore` have **byte-identical operand strings** with
different meanings. Any tool that returns the operand without its owning tag hands the
caller an ambiguous key and invites cross-attribution.

### 2.4 No reconciliation primitive

`audit_opc_item_paths` is the same *shape* of problem — compare an external list to the
project — but is hardwired to OPC paths. Every OEM line in this fleet ships a variables
list that has drifted from the code; there is no general "reconcile this column of tag
names against the project" tool.

### 2.5 Adding a tool is disproportionately expensive

`inputSchema` lives in a ~400-line `if name == ... elif name == ...` chain inside
`handle_mcp_request`'s `tools/list` branch, physically separated from both the handler and
the `add_tool` registration. Three edits in two distant places per tool. This is a direct
tax on the rest of this spec and should be paid down first.

## 3. Scope

**In scope:** a new `src/interface_audit/` package, five MCP tools, one CLI, the
`write_analyzer` extensions they depend on, and a UDT byte-layout model (§4.1e).

**Out of scope:** live-controller verification, ACD parsing changes, the comment-authoring
pipeline, HTML documentation rendering, anything requiring the Studio 5000 SDK
(`STUDIO5000_SDK_ENABLED` stays `false`).

## 4. Deliverables

### 4.0 Prerequisite: schema registry refactor

Move each tool's `inputSchema` next to its `add_tool` call. Extend
`MCPServer.add_tool(name, description, handler, input_schema=None)` to store the schema;
have `tools/list` iterate `self.tools` and emit the stored schema. Migrate the existing
`if/elif` chain mechanically. No behaviour change; `--test` output must be identical, and
a test should assert every registered tool has a non-empty schema.

### 4.1 `write_analyzer` extensions

Extend the existing module rather than forking it. Preserve the existing Ignition results
through an explicit `compatibility="legacy_ignition"` mode, selected by its callers.
That mode retains the historical instruction coverage, naming heuristics and boolean
aggregation. The audit mode uses the richer structural records and scope-aware resolution;
newly detected writes must not silently change the legacy export filter. Share parsing and
instruction metadata where possible, with the compatibility projection tested separately.

**a. Add the data-movement instructions** with operand *positions*, not just a destination
capture. A shared table replaces the two divergent regex sets:

| Instruction | Signature | Source | Dest | Length | Notes |
|---|---|---|---|---|---|
| `COP` | `(src, dest, len)` | 0 | 1 | 2 | length counts **destination** elements — see §7 |
| `CPS` | `(src, dest, len)` | 0 | 1 | 2 | synchronous copy, same arithmetic |
| `FLL` | `(src, dest, len)` | 0 | 1 | 2 | source is a scalar |
| `BTD` | `(src, srcBit, dest, destBit, len)` | 0 | 2 | 4 | bit-level; already partly handled |
| `MOV`/`MVM` | `(src, [mask,] dest)` | 0 | last | — | existing |
| `CLR` | `(dest)` | — | 0 | — | existing |
| `MSG` | `(ctrl)` | — | per config | — | destination comes from the MSG config, not the rung |

**b. Record writes structurally.** Add a parallel `writes: List[TagWrite]` where

```python
@dataclass(frozen=True)
class TagWrite:
    tag: str              # destination operand exactly as written, e.g. "MES.Allarm[1]"
    base_tag: str         # "MES.Allarm"
    bit: int | None       # 12 for MES.LineState.12, else None
    instruction: str      # "COP"
    program: str | None   # program containing the writer, if applicable
    routine: str          # "Zona_Carico_Mes"
    rung: int | None      # 13 for RLL; ST carries a separate source span
    scope: str            # destination declaration scope: controller | program | aoi
    tag_id: str           # canonical scope-qualified destination identity
    task: str | None      # owning task, resolved via Program -> Task
    operand_role: str     # "destination" | "aoi_output" | "timer_implicit"
    length: int | None    # literal COP/CPS/FLL/BTD length, if constant
    length_expr: str|None # the operand text when it is not a literal
    raw_text: str         # the rung's neutral text
```

**c. Cover the write paths the naive regex misses.** Each must be detected and, where
detection is not possible, explicitly reported as an unknown rather than silently absent:

- Indirect/indexed destinations (`MES.LineState[idx]`, `Arr[Tag]`) → report as
  `indeterminate` with the index expression.
- Whole-tag and whole-UDT writes that *contain* the queried bit (a `COP` onto `MES`, or a
  `MOV` to `MES.LineState` covering all 32 bits).
- **Overrun-implied writes**: a `COP` whose destination window extends past the declared
  dimension into the *next UDT member*. Detect these in addition to explicit writers;
  the motivating project's J6 also has an explicit writer at rung 34.
- Alias tags resolving onto the target (`AliasFor` chains, transitively).
- AOI bodies, Function Block (`<FBDContent>`) and Structured Text (`<STContent>`) routines —
  the current code only reads `<Rung><Text>`. ST assignment targets and FBD output pins
  must at minimum be reported as `unparsed_language` so the caller knows coverage is partial.
- Produced/consumed tags and controller-scope `MSG` destinations.
- Periodic/Event tasks (affects whether a bit is re-evaluated every scan — see §4.2 note
  on latched-vs-cleared).

**d. Drop the hardcoded prefixes.** Move `Com_AliasDIn_`/`Htr1_`/`Cmd_`/`Set_` into an
optional `naming_profile` argument with a documented audit-mode default of `None`
(classify I/O by `AliasFor` containing `:I`/`:O` and by module membership instead).
The explicit legacy Ignition mode retains its existing naming profile and results.

**e. UDT byte-layout model** (`src/interface_audit/layout.py`). Every overrun finding must
name the members a copy window actually lands on, and that needs byte offsets. Implement
Logix layout rules from the `<DataType>` definitions: members in declaration order, BOOLs
packed into the hidden `ZZZZZZZZZZ…` SINT members (the L5X already emits them with
`Hidden="true"`), SINT/INT/DINT/REAL natural alignment, nested structures and arrays,
4-byte end padding. Provide `offset_of(udt, member_path)`, `size_of(type)` and
`members_in_window(udt, start_byte, n_bytes)`. Validate against the motivating project:
`DatiScambioCED.Allarm[49]` ends at byte 203, `RobotMissionCountToUnloadEmptyRods` at 204,
`RobotMissionCountToLoadFullRods` at 206.

**f. Parse Structured Text writes.** Handle `target := expr;`, `target.bit := …`, and
instruction calls such as `COP(source, dest, 1);` using the shared operand-role table.
Respect comments, strings, nested operands and statement boundaries; attach source spans
and enclosing conditions. Unsupported ST constructs, unknown instruction effects and FBD
must remain explicit coverage gaps rather than being treated as fully parsed languages.

**g. Stored values and provenance.** Resolve scalar, member, array and bit values from
both `<Data Format="L5K">` and `Format="Decorated"` through the shared value-reading path.
Every row carries `stored_value` (nullable), `value_origin` (`exported`, `synthesized`, or
`unavailable`), source file/hash, data format and available export/conversion metadata.
Conflicting representations or unknown conversion provenance produce an unavailable value
with a reason; absence is never silently converted to zero.

The current offline ACD exporter generates initialization values, including scalar zeros
and Decorated structures/arrays. Mark these `synthesized`; they cannot substantiate zero,
constant, frozen or runtime counter findings. Known native export values are snapshots,
not live values. The motivating audits' native values and historian observations remain
separate evidence. No ACD parser changes are required for this provenance contract.

**h. Tag scope and external path.** Every result carries `scope` and the OPC/Logix path
(`Program:MainProgram.MES`, not `MES`). Both MES tags in the fleet are program-scoped and
neither vendor sheet nor the first corrected sheet said so.

Scope is part of identity and lookup, not only output. Use case-insensitive canonical
identities that retain declaration scope, program/AOI owner, array indices and member/bit
paths; preserve original spelling for display. Resolve operands in their writer's lexical
scope (program-local before controller scope), and resolve aliases transitively with cycle
detection. AOI locals/parameters require instance and call-site context when attributing
writes to caller tags. Never use `_clean_tag_ref` as an audit identity.

Public tag-taking tools accept qualified paths and an optional `program` context. An
unqualified public query without context resolves only when unique; otherwise return
`AMBIGUOUS_TAG` with qualified candidates, without merging writers. Routine selectors
similarly require an owner when names collide. Propagate this context through CLI/report
composition and reference-list reconciliation.

**i. I/O operand resolution.** When a writer's condition or a destination is a module point
(`IO_Interface:8:I.1`), return the module catalog number, slot, point number, any point
comment, and the print-style identifier (`I00_05_08.01`) when the module name encodes it.
The meaning of `LineState.8-11` on the loader (Handtmann linker handshake) came only from
the electrical prints; the tool must at least hand the caller the key to look it up.

### 4.2 Tool: `find_tag_writers`

```
find_tag_writers(
  project: str,                  # .l5x or .ACD path
  tag: str,                      # qualified path, or unique name with optional context
  program: str | null = null,
  bit_level: bool = true,        # expand a DINT/INT/SINT into per-bit rows
  include_indirect: bool = true,
  include_overrun: bool = true,
  source_depth: int = 8,
  source_node_limit: int = 1000
)
```

Returns, per bit or per member:

```json
{
  "tag": "MES.LineState",
  "data_type": "DINT",
  "declared_in": "DataType DatiScambioCED, member LineState",
  "coverage": { "complete_for_query": true, "unparsed_routines": [], "unknown_effects": [] },
  "bits": [
    { "bit": 0, "writers": [ { "instruction": "OTE", "program": "MainProgram",
        "routine": "Zona_Carico_Mes", "rung": 0, "scope": "program",
        "task": "MainTask", "condition": "XIC(IO_Interface:1:I.0)",
        "raw_text": "XIC(IO_Interface:1:I.0)OTE(MES.LineState.0);" } ] },
    { "bit": 12, "writers": [], "verdict": "NO_STATIC_WRITER_FOUND",
      "stored_value": 0,
      "value_origin": "exported",
      "note": "No static writer found with complete coverage for this query. The exported bit is 0; retained values and external writes can still change its runtime value." }
  ]
}
```

An empty writer list yields `NO_STATIC_WRITER_FOUND` only with complete static coverage
for the queried storage; otherwise return `UNKNOWN` and the specific gaps. Indirect writes,
unsupported instructions/languages, unresolved aliases/AOI bindings and omitted regions
(including caller-disabled indirect/overrun analysis) must propagate uncertainty. Account
for I/O, consumed tags and resolved MSG writes as producer kinds, and separately report
external-write capability or uncertainty. No static writer does not mean constant.

Rows carry value provenance and the retained-value caveat from §4.1g. The reported native
snapshot (`LineState` = 67) and 30 days without observed bits 12/13 support only those
observations, not a claim that the bits are permanently zero.

`condition` is the rung's input branch, verbatim — enough to describe the bit without a
second call. This single tool replaces §2.1's unsound grep and collapses the LineState
table to one call.

Each writer also returns **both comments** that describe it: `rung_comment` (the comment on
the rung holding the OTE) and `operand_comment` (the comment stored on the destination
operand of the tag). On the loader these disagree for eleven alarm bits — the tag comments
on `Dati_Zona_Carico.Allarmi_Zona[2].0-.2` are shifted one bit from the rungs that drive
them, `[3].0-.4` carry numbers one too high, `[0].15` describes a Handtmann mat while the
rung drives a gate — and the first corrected sheet copied the stale tag comments. The tool
must surface both so the agent cannot silently pick one.

Add `source_writers` to every data-movement writer: for a `COP`/`CPS`/`MOV`, recursively
answer "who writes the source?". Track canonical storage identities and call contexts in
the active traversal; emit a `cycle_ref` on a back edge and reuse stable node references
for shared dependencies. Enforce the requested depth/node limits, deterministic traversal
order and an explicit `truncated` reason. Cycles or limits never imply an unwritten source.
Propagate coverage and provenance at each node. The robot-joint sources have no identified
static writers in the audits; their unchanged historian values are separate, window-bound
observations, not proof of a constant source.

### 4.3 Tool: `audit_data_movement`

```
audit_data_movement(
  project: str,
  scope: str = "all",            # "all" | program | routine name
  severity_min: str = "info"
)
```

Walks every instruction in the §4.1(a) table, resolves each operand's declared dimension
and element size through the UDT/module definitions, and reports:

| Check | Finding |
|---|---|
| `OVERRUN_MEMBER` | copy window exceeds the destination member's declared dimension and, per §7, continues into the following members of the same base tag; the finding lists those members by name from the §4.1e layout |
| `OVERRUN_TAG` | window would exceed the base tag; per §7 the controller clamps, so severity is *info* and the finding says which bytes are dropped |
| `OVERRUN_SRC` | window reads past the source member's end; if it also reaches past the source *tag*, say whether the controller family clamps it (§7) rather than asserting a garbage read |
| `OVERLAP` | two copies in the same routine write intersecting destination windows |
| `TYPE_MISMATCH` | source and destination element sizes differ, so `length` means different byte counts on each side |
| `SHADOWED` | a later write is proven to overwrite the earlier value on every relevant execution path before the stated observation point; otherwise report only `OVERLAP` with uncertain effect |
| `SUSPICIOUS_LENGTH` | `length > 1` onto a scalar destination |
| `NO_STATIC_WRITER_FOUND` | the source of a `COP`/`CPS`/`MOV` has no identified static writer with complete query coverage; external changes remain possible. Incomplete coverage yields `UNKNOWN` |
| `MSG_DEST_MISMATCH` | a `MESSAGE` tag whose `DestinationTag` does not share the message tag's stem (`U6_ReadCurrent_MSG` → `U5_ReadCurrent`) |
| `MSG_DEST_TYPE` | a CIP Generic read whose destination type cannot hold the reply as written: class `0x93` (DPI parameter object) attribute 9 returns a 16-bit value, and six REAL destinations on each line hold exactly 10.0 |
| `COUNTER_WRAP` | an `ADD(x,1,x)` or `CTU` on an INT/SINT with no `MOV`/`CLR`/reset anywhere; the unloader's `StepOfBeltCutterFilledCount` is already at -1593 |
| `ONS_REUSE` | the same storage bit used by two `ONS`/`OSR`/`OSF` instructions |
| `COMMENT_CONFLICT` | for alarm-style bit arrays: the number parsed from the driving rung's comment, the number in the operand's tag comment, and `bit+1` disagree; also a tag comment on a bit with no writer, and a driven bit with no comment anywhere |

Each finding carries `{severity, instruction, program, routine, rung, source, dest, length,
source_dim, dest_dim, element_bytes, affected_bytes, affected_members, stored_values,
explanation, suggested_fix, controller_family, semantics_ref}`.
For `OVERLAP` and `SHADOWED`, rung order within the routine must be part of the evidence.
`OVERLAP` is a structural intersection, not proof of data loss. Definite shadowing requires
the task/program/call path, execution conditions, branch/jump/return effects, and intervening
reads to be resolved. State `observation_point` (for example, return from the MES routine),
`confidence`, assumptions and supporting locations. An intervening consumer prevents a
claim that the value was never observable, even if it is overwritten at routine return.
Unresolved scheduling or external observation timing remains unknown; scan order alone
does not prove what an asynchronous MES client can read.
`semantics_ref` cites the entry in `semantics.py` (§7) the verdict rests on.

Against the loader project this must produce, without prompting:

- `OVERLAP` + `OVERRUN_MEMBER` on `Zona_Carico_Mes` rungs 12–13: `COP(Dati_Zona_Ribaltatore.Allarmi_Zona[0], MES.Allarm[1], 50)`
  writes 200 bytes from offset 8; bytes 8–203 are `Allarm[1..49]`, bytes 204–207 are
  `RobotMissionCountToUnloadEmptyRods` and `RobotMissionCountToLoadFullRods`. Both counters
  are zeroed every scan (tipper word 49 is never set). Stored values 0 and 0 beside
  `NumberOfRackLoaded` = 1726 are the evidence, and the historian confirmed it (30 days, max 1).
  **Not** "one element past the end of the array" — that was the first draft's error.
- `NO_STATIC_WRITER_FOUND` ×6 on the robot-position rungs, subject to complete source coverage.
  The five length-2 copies overlap; classify their overwritten portions as `SHADOWED` only
  with the execution evidence above. Rung 34 explicitly writes J6; do not infer harmlessness
  for intervening or asynchronous readers.
  The first draft's "J6 written only as overrun of J5" is false.
- `MSG_DEST_MISMATCH` ×2 (`U6_ReadCurrent_MSG`, `U6_ReadFault_MSG` → `U5_*`) and
  `MSG_DEST_TYPE` ×6 (REAL destinations at 10.0; `MES.UxCurrent` never left 0 in 30 days).
- `OVERRUN_SRC` ×6 on the `MES.UxSpeed` rungs, reported as *controller-dependent*
  (5069-L310ERS2 is a 5380; Rockwell bounds the copy by the source tag size for mixed types
  and says nothing for same-type). Severity info; rungs 41–51
  rewrite `UxCurrent` in the same scan, subject to proving execution and the stated
  observation point; this does not establish harmlessness for all readers.

Against the unloader project:

- No alarm finding (single-zone `COP` of 50 into 50 — the negative control).
- `OVERRUN_SRC` on `LineaScarico_Mes` r37 `COP(MES.NumberOfRackUnLoaded, MES.RackUnloadedCounter, 2)`:
  source is the last member of MES; if two elements are copied, `RodsUnloadedCounter` is
  clobbered on every rack event (stored 4 beside 2108 racks).
- `COUNTER_WRAP` on `StepOfBeltCutterFilledCount` (stored -1593) and on both mission counters.
- `NO_STATIC_WRITER_FOUND` ×6 (same source-coverage requirement for `PosRobotGiunti`),
  `MSG_DEST_TYPE` ×5, no `MSG_DEST_MISMATCH`.

These are the spec's primary acceptance criterion. Finding them must not require the
caller to suspect anything, and the loader/unloader pair must produce the *different*
verdicts listed.

### 4.4 Tool: `reconcile_tag_list`

```
reconcile_tag_list(
  project: str,
  list_path: str,                # .xlsx | .csv
  sheet: str | null = null,
  tag_column: str | int,
  description_column: str | int | null,
  type_column: str | int | null,
  expand_bits: bool = true       # "MES.LineState.8" matches a DINT member's bit 8
)
```

Per row, one of:

- `VERIFIED` — tag exists, is written, and the declared type matches.
- `TYPE_MISMATCH` — exists, declared type differs from the UDT.
- `NOT_WRITTEN` — exists, with `NO_STATIC_WRITER_FOUND` under complete static coverage;
  this verdict is limited to analyzed project logic, not external/runtime writes.
- `UNKNOWN` — coverage, execution or identity cannot be resolved; include reasons and,
  for `AMBIGUOUS_TAG`, qualified candidates. Never promote uncertainty to `VERIFIED`.
- `NOT_FOUND` — no such tag or member.
- `OVERWRITTEN_AT_OBSERVATION` — a source value is proven overwritten at the specified
  observation point under §4.3's execution rules. Include source-to-destination mapping
  and evidence; this does not mean no intermediate or external reader could observe it.
  The loader's lost loading-zone alarm mappings belong here when proven at routine return.

Plus the inverse: `UNDOCUMENTED` for members of a named UDT absent from the list. The
motivating job needed this to notice the old sheet left every `MES.UxFault` description
blank, and both the old and the first corrected loader sheet omitted five written members
(`NumberOfPoleOnRack1..3`, `NumberOfRackLoaded`, `NumberOfRackUnLoaded`).

`NOT_WRITTEN` must also apply to individual alarm bits that no rung drives (loader
`Dati_Zona_Carico.Allarmi_Zona[2].3` and `Dati_Zona_Ribaltatore.Allarmi_Zona[2].0` both carry
tag comments and appeared in the corrected sheet, but nothing drives them). And a second
inverse, `UNDOCUMENTED_BIT`, for driven alarm bits with no comment: the loader has 8 in the
loading zone and 8 in the tipper zone (including the VFD U4/U5/U6 faults), the unloader 6.

Every row carries `scope`, `path`, `stored_value`, value provenance, coverage and, for bits,
both comments from §4.2. An existing destination can be written from a different source;
retain the documented source mapping so its loss is not hidden by destination writtenness.

A companion `reconcile_alarm_numbers(project, tag, reference_list)` takes an external alarm
list (fault guide headings, HMI alarm export, or the `MES Fault Code Extraction.xlsx` style)
and reports, per PLC alarm number, whether the reference number, text and bit agree with
the driving rung. Both fleets have this problem: the loader fault guide numbers tipper alarms
A1001+ while the HMI list uses A001+; the unloader fault guide uses different numbers from
the PLC between 021 and 062, and its in-house extraction workbook puts about a dozen alarms
on the wrong bit.

The tool must **not** attempt to judge whether a prose description matches the logic — that
is the agent's job. It reports existence, type, writtenness and reachability only.

### 4.5 Tool: `get_rung`

```
get_rung(project, routine, rung: int | "a-b" | null, program: str | null = null)
```

Returns decoded neutral text (CDATA stripped, `&#10;` resolved), the rung comment, the
enclosing program/routine/task, and the resolved description of every operand. Also accept
a `contains` filter as a replacement for the raw-XML path of `search_l5x_content`.
`search_l5x_content` keeps its current output for compatibility but gains
`format: "neutral" | "xml"` defaulting to `xml`. Neutral output is opt-in for this existing
tool; the new `get_rung` tool returns neutral text by default.

### 4.6 Comment attribution fix

Every comment-returning tool gains a fully-qualified operand:
`Dati_Zona_Carico.Allarmi_Zona[0].0` rather than `.ALLARMI_ZONA[0].0`, with the owning tag
and scope as separate fields. Preserve the original casing alongside the uppercased
operand — the L5X stores operands uppercased while `<Tag Name>` is mixed case, and callers
need both to build valid tag paths.

### 4.6a Tool: `compare_routine`

```
compare_routine(project_a, project_b, routine, program: str | null = null)
```

Returns a rung-by-rung diff of neutral text and comments, plus a diff of the UDTs and tag
comments the routine touches. Six loaders and six unloaders share `DatiScambioCED`; the
unloader audit was done by hand-diffing lxml dumps against the loader, and establishing
"which file runs" needed a diff of three exports of the same project (Nov 2025 l5x,
Jan 2026 L5K, Jun 2026 ACD export). Also print `ExportDate`, `LastModifiedDate` and the
ACD mtime, and warn when the L5X predates the ACD.

### 4.7 CLI: `plc-audit`

Follows the `scripts/plc_docgen.py` + `[project.scripts]` pattern exactly
(`plc-audit = "interface_audit.cli:main"`, added to `packages.find.include`).

```
plc-audit writers  <project> --tag MES.LineState --bit-level [--json]
plc-audit movement <project> [--scope Zona_Carico_Mes] [--severity warning] [--json]
plc-audit reconcile <project> --list vars.xlsx --tag-column A [--desc-column C] [--json]
plc-audit report   <project> --list vars.xlsx --udt DatiScambioCED --out corrected.xlsx
```

`report` is the whole motivating job in one command. It emits the workbook the agent built
by hand: an About/provenance tab, a per-bit tab with a status-vs-source column, an
alarm-bit tab with PLC comments and reachability, an other-members tab, and a defects tab
fed by `audit_data_movement`. Templated in `src/interface_audit/report_template.py`, no
LLM, deterministic output for a given input pair — so it can be diffed in CI.

Every subcommand takes `--json` and prints the tool's payload verbatim, so an agent can
call the CLI or the MCP tool interchangeably and the CLI is testable without a server.

### 4.8 Tool: `describe_interface_tag` (the composing call)

```
describe_interface_tag(project, tag)        # "MES", or any UDT-typed tag
```

One call that produces what the two audits actually delivered: for every member (and every bit
of every DINT/INT member that has bit-level writers) — writers with rung, condition, both
comments and `source_writers`; stored value; scope and external path; the UDT member
description; the §4.3 findings that touch it; and a `verdict` from
`{LIVE, NO_STATIC_WRITER_FOUND, UNKNOWN, OVERWRITTEN_AT_OBSERVATION, DEAD_BY_TYPE,
CONTROLLER_DEPENDENT}`. `LIVE` means a resolved static producer, not observed runtime
activity. All rows inherit scope resolution, coverage, value provenance and bounded source
tracing from §4.1–4.3. `DEAD_BY_TYPE` requires a proven end-to-end type effect; an isolated
type mismatch remains a finding with uncertain downstream effect. Historian observations
are attached separately and do not turn an empty writer list into `CONSTANT`.
Everything else in §4 is a building block for this. Its markdown rendering (`--format md`)
is the handoff-document table; both handoffs written on 2026-09-17 were assembled by hand
from exactly these fields.

### 4.9 Tool: `extract_alarm_map`

```
extract_alarm_map(project, tag)             # "Dati_Zona_Carico.Allarmi_Zona"
```

For an alarm bit array: per driven bit — word, bit, `bit+1`, rung, rung comment, number
parsed from the rung comment, tag comment, number parsed from the tag comment, the rung's
input condition with I/O operands resolved (§4.1i), the `Timeout[n].BitTimeOut` or other
named source with its description, the ack bit, and `COMMENT_CONFLICT` flags. Also the
list of commented-but-undriven bits and driven-but-uncommented bits. This table was built
three times by hand today (loader loading zone, loader tipper zone, unloader) and is the
input `reconcile_alarm_numbers` and the Ignition alarm tags need.

### 4.10 Tool: `audit_messages`

```
audit_messages(project)
```

Per `MESSAGE` tag: trigger rung and pattern (`XIO(.EN) MSG` self-retrigger, edge, timer,
none), connection path and whether the module exists, decoded service/class/instance/
attribute (class `0x93` instance N → "PowerFlex DPI parameter N", with the known PF52x
parameter names for 1-10), expected reply size, destination tag, its type and stored value,
`MSG_DEST_MISMATCH`, `MSG_DEST_TYPE`, and `MSG_DEST_SHARED` (two messages writing one
destination — `U5_ReadCurrent` receives U5 and U6 on every loader line). Also whether the
`.ER`/`.ERR` values are present in the export.

### 4.11 Tool: `project_provenance`

```
project_provenance(paths: list[str])
```

For each L5X/L5K/ACD: `ExportDate`, `LastModifiedDate`, `ProcessorType`, controller
family, `ProjectSN`, file mtime, git status (LFS pointer versus smudged content, committed
oid, last DeviceLink commit touching the ACD). For a list: which of them are the same
project, and a diff of routines, UDTs and tag comments between any two (§4.6a). Answers
"is the file I am auditing the one that runs?" — the first question in both audits, and one
that needed `git lfs smudge` by hand. Warn when only an ACD exists and
`STUDIO5000_SDK_ENABLED` is false, so the caller knows an export is required.

### 4.12 Reference-document ingestion

`src/interface_audit/references.py` loads the documents every OEM line ships, into one
normalised shape `{number, text, source, page}` for alarms and `{point_id, tag, description,
device}` for I/O:

- vendor variables lists (`.xlsx`, the `Variable | Type | Description` layout);
- fault guides (`.doc` via `antiword`, `.docx` via zip/XML) — heading regex `A?\d{3,4} - text`;
- HMI alarm exports and the in-house `MES Fault Code Extraction.xlsx` style;
- I/O lists (`Vemac_Unloading_Line_PLC_IO_List.xlsx`) and electrical prints (`pdftotext
  -layout`, reuse the existing `index_pdf_drawings` path) for `I00_05_08.01`-style identifiers.

`reconcile_tag_list` and `reconcile_alarm_numbers` consume these; nothing else parses
documents. Declare `antiword` and `pdftotext` as optional dependencies with a clear error.

### 4.13 Verification plan and historian round-trip

Every §4.3 finding and every `describe_interface_tag` verdict that rests on inference
(`OVERWRITTEN_AT_OBSERVATION`, `DEAD_BY_TYPE`, `NO_STATIC_WRITER_FOUND`, `UNKNOWN`,
`CONTROLLER_DEPENDENT`) also emits a
`verification` block: the tags to trend, the window, and the signature that confirms or
refutes it ("counter never exceeds 1 while `NumberOfRackLoaded` climbs", "six REAL tags stay
exactly 10.0", "J1..J6 have one distinct value"). `plc-audit verify-plan` prints them as a
prompt for a historian agent. `plc-audit verify-apply --results results.csv` (per tag:
min, max, distinct, first, last) marks each finding `CONFIRMED`/`REFUTED`/`INCONCLUSIVE`.
These statuses apply to the stated observation over the supplied window, not to a universal
runtime claim or proof of causation. Carry project/tag identity, time window, sample count,
quality and sampling details with imported results. Missing evidence is `INCONCLUSIVE`;
min/max/distinct alone cannot establish execution order, absence of transient values or
cross-tag correlation. A constant observed joint value does not prove no external writer.

### 4.14 Additional checks for §4.3

| Check | Finding |
|---|---|
| `INTEGER_TRUNCATION` | `DIV`/`MUL` into an INT/DINT whose result is provably < 1 for the source's stored or plausible range (`DIV(10.0, 100, INT)` = 0 on every drive current) |
| `NO_STATIC_WRITER_FOUND` | UDT instance members with no identified static writer under complete query coverage (`MES.U6*` on the unloader); otherwise `UNKNOWN` |
| `UNCONDITIONAL_CALL` / `CONDITIONAL_CALL` | whether the routine that writes the interface is reached by an unconditional `JSR` every scan; report the call path (`MainRoutine r9` on the loader, `LineaScarico_Generale r24` on the unloader) |
| `EDGE_SEMANTICS` | for `ONS`-gated counters, the exact condition that constitutes one count, and whether the condition can change value without dropping (missions 1→2 would not re-fire the loader's `Fronti[21]`) |
| `RESET_OVERRUN` | `FLL`/`COP` used as a reset whose window crosses into the next member (`FLL(AzzeraAllarmi, Allarmi_Zona[1..5], 50)` wipes `AckAllarmi_Zona` on the unloader) |
| `FROZEN_VALUE` | informational: a member whose stored value looks like a date or a placeholder (`BlendIdActive` = "09072025"); pairs with §4.13 |

### 4.15 Engineering constraints

- **Encoding.** Read the L5X as UTF-8 and emit UTF-8; test with `Velocità`. The console
  mojibake that made one auditor suspect data loss must not reach tool output.
- **Caching.** Parse a 2 MB L5X once per file hash and reuse across calls; `get_cache_performance`
  already exists.
- **Reuse.** `stored_value` goes through the existing `get_tag_value` path; I/O resolution through
  `get_module_tags`/`find_i_o_point`; prints through `index_pdf_drawings`. Do not fork them.
  Extend the shared value path/adaptor as needed for both data formats and §4.1g provenance;
  synthesized ACD initialization must not become runtime evidence through this reuse.
- **No unit conversion, no prose judgement** (§8). The tool may quote a UDT member description
  or a rung comment; it may not paraphrase it.
- **Determinism.** Same inputs, byte-identical output, so handoff tables diff cleanly in git.

## 5. Phasing

| Phase | Content | Unblocks |
|---|---|---|
| 0 | §4.0 schema registry refactor; fix the empty `get_instruction("COP")` index entry | cheap tool addition |
| 1 | §4.1 write_analyzer extensions, `TagWrite`, ST parsing, stored values, UDT layout (§4.1e) | everything |
| 2 | §4.2 `find_tag_writers` (both comments, `source_writers`, I/O resolution), §4.5 `get_rung`, §4.6 comment qualification | the common case |
| 3 | §4.3 `audit_data_movement` with all thirteen checks, `semantics.py` from §7 | the defect classes that needed luck or history |
| 4 | §4.9 `extract_alarm_map`, §4.10 `audit_messages`, §4.11 `project_provenance`, §4.14 extra checks | the checks that found the real defects |
| 5 | §4.8 `describe_interface_tag`, §4.12 reference ingestion, §4.4 `reconcile_tag_list` + `reconcile_alarm_numbers`, §4.6a `compare_routine`, §4.7 `plc-audit report` | the full job in one call |
| 6 | §4.13 verification plan and historian round-trip | inference becomes evidence |

Phases 1–4 carry the value. Phase 5 is what makes the job one call instead of ten; phase 6
is what makes the output trustworthy without a second auditor.

## 6. Acceptance tests

Two synthetic or sanitized, non-proprietary golden fixtures in `tests/interface_audit/`
model the loader `PLC_IsolaCaricoSalami1.l5x` and unloader `PLC_IsolaScaricoSalami.L5X`.
Do not commit customer PLC exports, workbooks, historian data or vendor documents. Keep
private integration inputs outside the tracked tree and skip those tests explicitly when
unavailable. Recreate the relevant behavior in public fixtures, including the MES
routine, the `DatiScambioCED`/`DatiScambioCed` UDT with its hidden members, the zone tags
with their comments, the alarm routines, the MSG tags with their `MessageParameters`, the
`Gestione_Robot` tags, and one PowerFlex module. Do not hard-code counts copied from an
agent's report; derive independent expected values from documented fixture logic and cite
the rung. Never compute the expected answer using the analyzer under test. The named
customer-file checks below are private integration checks; public fixtures independently
exercise the same rules with their own expected values.

1. `find_tag_writers(tag="MES.LineState", bit_level=True)` on the loader → exactly bits
   0–11 have writers; 12–13 `NO_STATIC_WRITER_FOUND` with native `stored_value` 0 and
   `value_origin="exported"`; 14–31 none. On the
   unloader → bits 0–3, 5, 8–13. Every writer row carries scope `program` and path
   `Program:MainProgram.MES`.
2. Bit 10's writer (loader) records **both** `IO_Interface:8:I.1` and `:8:I.2` as a series
   AND, and resolves them to point identifiers `I00_05_08.01` / `.02`.
3. `audit_data_movement` returns every finding listed in §4.3 for both fixtures, the
   loader alarm `OVERLAP`/`OVERRUN_MEMBER` ranked highest, `affected_members` naming the two
   mission counters, and nothing on the unloader alarm COP.
4. `find_tag_writers("MES.RobotJ1Position")` returns the rung-29 COP with
   `source_writers: []` with complete source coverage, on both fixtures; an empty list
   without complete coverage must instead yield `UNKNOWN`.
5. `reconcile_tag_list` against `LoadingVariablesList.xlsx` → bit 0 `VERIFIED`; bits 1–11
   `VERIFIED` on existence; 12–13 `NOT_WRITTEN`; every loading-zone alarm bit in words 1–3
   `OVERWRITTEN_AT_OBSERVATION` with the MES routine return and proven execution paths
   specified; every `MES.UxFault` description-missing; five `UNDOCUMENTED` members.
6. Comment extraction returns the tag comments qualified to `Dati_Zona_Carico` and
   `Dati_Zona_Ribaltatore` with zero cross-attribution, and `COMMENT_CONFLICT` fires on
   loader `[0].15`, `[2].0`, `[2].1`, `[2].2`, `[2].23`–`[2].25`, `[3].0`–`[3].4`, on the
   two commented-but-undriven bits, and on none of the unloader bits (its rung numbers
   equal `bit+1` throughout).
7. `reconcile_alarm_numbers` against the unloader fault-guide headings flags 033–036,
   038, 047–055 as renumbered and 063+ as matching.
8. Explicit `legacy_ignition` mode returns identical `is_written()` results for existing
   Ignition fixtures, including naming-only setpoints and COP-only destinations. Audit mode
   independently detects the COP and does not infer a writer from naming alone.
9. `plc-audit report` is byte-stable across two runs on the same inputs.
10. `python src/mcp_server/studio5000_mcp_server.py --test` still passes and stays fast
    (lazy-init preserved; no L5X parsing at registration time).
11. `get_instruction("COP")` returns a non-empty description and parameters. Today it
    returns `description: "Index"`, `parameters: null` — the help index has nothing for COP,
    so §7 cannot be "resolved from `get_instruction`" until that is fixed.
12. `audit_messages` on the loader → `MSG_DEST_MISMATCH` ×2, `MSG_DEST_SHARED` on
    `U5_ReadCurrent` and `U5_ReadFault`, `MSG_DEST_TYPE` ×6, trigger pattern `self_retrigger`
    on all twelve; on the unloader → `MSG_DEST_TYPE` ×5 and nothing else.
13. `extract_alarm_map` on loader `Dati_Zona_Carico.Allarmi_Zona` → 67 driven bits, 60 tag
    comments, `COMMENT_CONFLICT` on the eleven bits listed in test 6, one commented-undriven
    bit; on `Dati_Zona_Ribaltatore.Allarmi_Zona` → 28 driven, 21 commented, 8 driven-uncommented;
    on unloader `Dati_Zona_Scarico.Allarmi_Zona` → 117 driven, 5 commented, 6 driven bits with
    an empty rung comment (85, 115, 116, 129-131).
14. `project_provenance` on the three loader exports (Nov 2025 l5x, Jan 2026 L5K, Jun 2026
    ACD export) reports one project, identical `Zona_Carico_Mes`, and lists the three
    routines that differ. On the six loader lines it reports identical `Zona_Carico_Mes`
    rungs 8-13 and identical MSG wiring.
15. `describe_interface_tag("MES")` on the loader gives verdicts: `LineState` bits 0-11 `LIVE`,
    12-31 `NO_STATIC_WRITER_FOUND` with complete coverage; `Allarm[0]` `LIVE`,
    `Allarm[1..49]` `LIVE` with source `Dati_Zona_Ribaltatore`; both mission counters
    `OVERWRITTEN_AT_OBSERVATION` where proved at routine return; `U1..U6Current`
    `DEAD_BY_TYPE` only with end-to-end type evidence; `RobotJ1..J6Position` have a copy
    writer and a source finding `NO_STATIC_WRITER_FOUND`; `UxSpeed` `LIVE` with an `OVERRUN_SRC`
    `CONTROLLER_DEPENDENT` note. On the unloader: `RodsUnloadedCounter` `CONTROLLER_DEPENDENT`,
    `StepOfBeltCutterFilledCount` `LIVE` + `COUNTER_WRAP`, `U6*` `NO_STATIC_WRITER_FOUND`
    with complete coverage. Incomplete evidence yields `UNKNOWN`, not forced golden verdicts.
16. `plc-audit verify-plan` on the loader emits, at minimum, the mission-counter, current,
    joint-position and LineState 12/13 checks; `verify-apply` with the 2026-09-17 historian
    results marks supported window-bound observations `CONFIRMED`, with metadata required
    by §4.13; insufficient sampling/correlation evidence remains `INCONCLUSIVE`.
17. Reference ingestion parses `LodingFauldGuide.doc` (A001-A081, A1001-A1058),
    `UnloadingFauldGuide.docx` (001-134), `Loading Line Alarms List_New.xlsx`, and
    `Vemac_Unloading_Line_PLC_IO_List.xlsx` (I00_05_08.03 = "Closed hands sensor").
18. Value fixtures cover L5K and Decorated scalar/member/array/bit values, conflicting or
    absent representations, native snapshots and synthesized ACD initialization. Synthetic
    zeros never support runtime findings; every output path preserves provenance.
19. ST instruction calls (including COP), commented-out assignments, unsupported effects,
    indirect writes and FBD coverage gaps cannot produce false unwritten/constant verdicts.
    Test consumed/I/O producers and external-write uncertainty separately.
20. Conditional later copies, skipped routines and intervening reads produce overlap without
    unsupported shadowing claims. An unconditional overwrite fixture proves the value at
    routine return while explicitly leaving asynchronous observation timing unknown.
21. Duplicate controller/program tag names resolve by lexical scope inside logic; unqualified
    public queries return `AMBIGUOUS_TAG`, and qualified queries never merge writers. Cover
    case variants, aliases and separate AOI instances with identical local names.
22. Self-copy, `MOV(A,B)`/`MOV(B,A)`, shared dependency diamonds and long source chains
    terminate deterministically with cycle references or explicit truncation. Limits and
    cycles cannot become `NO_STATIC_WRITER_FOUND` evidence.
23. Existing `search_l5x_content` calls retain XML output; explicit `format="neutral"` and
    new `get_rung` calls return decoded neutral text with context.

## 7. Semantics (resolved; encode in `src/interface_audit/semantics.py`)

**COP/CPS**, from the Rockwell Studio 5000 Logix Designer v37 instruction reference,
"Copy (COP) - Synchronous Copy (CPS)", read 2026-09-17:

- Length: "Number of Destination elements to copy".
- "The COP and CPS instructions operate on contiguous memory and perform a straight
  byte-to-byte memory copy."
- Bytes copied = the smaller of: Length × bytes per destination element; the bytes remaining
  in the destination tag; and, "for Compact GuardLogix 5380, CompactLogix 5380, CompactLogix
  5480, ControlLogix 5580, or GuardLogix 5580 controllers: the number of bytes in the source
  tag". Rockwell states this list under "when the Source and Dest are different data types";
  the same-type case is not stated, so the source bound must be reported as
  *controller-dependent and undocumented for same-type copies*.
- "The end of the destination or source tag is defined as the last byte of the base tag. If
  the tag is a structure, the end of the tag is the last byte of the last element of the
  structure. This means the COP and CPS instruction could write past the end of a member
  array but will never write past the end of the base tag."
- Faults: "None specific to this instruction."

Consequences the tool must encode: overrun continues into following UDT members (never a
fault, never a clamp at the member); clamps only at the base tag; the controller family is
read from `ProcessorType` and drives the source-bound verdict. The historian confirmed the
loader consequence (mission counters zeroed for 30 days beside climbing rack counters).

**MSG CIP Generic, class 0x93 attribute 9** (DPI parameter object, PowerFlex 52x): the reply
is the parameter's native size, 16-bit for b003 Output Current (resolution 0.01 A). A REAL
destination cannot receive it correctly. Encode as a `MSG_DEST_TYPE` rule; keep the
engineering-unit claim out of tool output.

**Drive input assembly `OutputFreq`**: 0.01 Hz raw. Confirmed from history (5000 while
running at 50 Hz). Report it as "raw drive units, see drive profile" rather than converting.

**Unverified and out of scope for the tool:** what a same-type COP does at the end of the
source tag on a 5380; the robot joint unit (nothing in the project writes the source).

**Other verified facts the earlier draft got wrong**, kept here so nobody re-learns them:

- `Zona_Sel_Lav` in `Generale_Zona` means **wash mode selected** (`Sel_Lav_VT` = "Ciclo
  Lavaggio Selezionato da VT", member text "Modalità funzionamento zona in lavaggio", rung
  comment "Zona in Lavaggio"). The first corrected loader sheet's "selected to RUN" for
  `LineState.3`/`.6` was wrong; the vendor sheet's "wash cycle" was right. Tools must return
  the UDT member description alongside the member name so an agent sees it.
- Loader `LineState.8-11` are the Handtmann linker handshake inputs/outputs
  (I00_05_08.00-.02, O00_05_16.02), not station states.
- Loader rung 34 explicitly writes `MES.RobotJ6Position`.

## 8. Non-goals

- No natural-language description generation. These tools report facts; the agent writes prose.
- No judgement on whether an existing prose description is *correct* — only whether the tag
  exists, is written, and is reachable.
- No live controller or SDK dependency.
- No changes to `analyze_comment_graph` or the documentation pipeline.
