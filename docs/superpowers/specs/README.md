# Technical Specifications Index & Audit Traceability Matrix

This directory contains formal engineering and architectural specifications addressing all deficiencies, bugs, features, and strategic improvements identified in [docs/ENGINEERING_AUDIT_2026.md](../../ENGINEERING_AUDIT_2026.md).

Implementation status for every spec is tracked in [../ROADMAP.md](../ROADMAP.md).
Delivered designs are archived under [../completed/](../completed/README.md).

---

## Specifications Overview

| Spec ID | Specification Document | Primary Subsystem | Priority | Key Issues / Audit References |
| :--- | :--- | :--- | :---: | :--- |
| **SPEC-01** | [01-deterministic-ast-cross-reference.md](./01-deterministic-ast-cross-reference.md) | `l5x_analyzer` | **P0 / Critical** | Issue #26, BUG-03 / Issue #12, §6, §13, Rank #1 |
| **SPEC-02** | [02-acd-patch-rungs-hex-substitution.md](./02-acd-patch-rungs-hex-substitution.md) | `acd` | **P0 / Critical** | BUG-01 / Issue #34, Issue #6, §6, §10, Rank #2 |
| **SPEC-03** | [03-direct-acd-comment-writer.md](./03-direct-acd-comment-writer.md) | `acd` | **P1 / High** | Issue #22, Issue #6, §7, §10, Rank #12 |
| **SPEC-04** | [04-acd-datatable-value-extraction.md](./04-acd-datatable-value-extraction.md) | `acd` | **P1 / High** | BUG-02 / Issue #23, §6, §11, Rank #18 |
| **SPEC-05** | [05-plc-static-analysis-linter.md](./05-plc-static-analysis-linter.md) | `verification` / `l5x_analyzer` | **P1 / High** | Issue #18, BUG-09, §8, §9, §12, Rank #4, #10, #14, #15, #16 |
| **SPEC-06** | [06-safe-modification-staging-diff.md](./06-safe-modification-staging-diff.md) | `l5x_analyzer` / `mcp_server` | **P0 / Critical** | Section §3, §28, Rank #5, #11 |
| **SPEC-07** | [07-equipment-liveness-classifier.md](./07-equipment-liveness-classifier.md) | `l5x_analyzer` | **P2 / Medium** | Issue #27, §16, Rank #6, #17 |
| **SPEC-08** | [08-scada-ignition-export-coverage-and-scaling.md](./08-scada-ignition-export-coverage-and-scaling.md) | `ignition_exporter` | **P1 / High** | Issue #10, Issue #24, Issue #25, Issue #29, §15, Rank #8, #21, #22, #23 |
| **SPEC-09** | [09-security-safe-cache-and-deserialization.md](./09-security-safe-cache-and-deserialization.md) | `security` / `mcp_server` | **P1 / High** | BUG-05 / Issue #36, §20, Rank #4, #25 |
| **SPEC-10** | [10-ci-and-build-infrastructure.md](./10-ci-and-build-infrastructure.md) | `ci` | **P1 / High** | BUG-10 / Issue #35, §23, Rank #3 |
| **SPEC-11** | [11-core-bugfixes-and-mcp-reliability.md](./11-core-bugfixes-and-mcp-reliability.md) | `code_generator` / `ai_assistant` / `l5x_analyzer` | **P1 / High** | BUG-04 (#37), BUG-06 (#38), BUG-07 (#39), BUG-08, BUG-09, Issue #5 |
| **SPEC-12** | [12-documentation-and-drawings-enhancement.md](./12-documentation-and-drawings-enhancement.md) | `documentation` / `drawings_analyzer` | **P2 / Medium** | Issue #19, §17, §18, §24, Rank #24 |
| **SPEC-13** | [13-interface-audit-engine.md](./13-interface-audit-engine.md) | `l5x_analyzer` / `verification` / `mcp_server` | **Proposed** | Interface/MES audit; must be reconciled with SPEC-01/05/07/08 before a plan is written (see [../ROADMAP.md](../ROADMAP.md) Phase 6) |

---

## Audit Deficiency Traceability Matrix

### 1. Confirmed Bugs (§6)

| Bug ID | Title | Spec Mapping |
| :--- | :--- | :--- |
| **BUG-01** | `patch_rungs` fails to substitute `@HEX@` object IDs for new tags | [SPEC-02 (02-acd-patch-rungs-hex-substitution.md)](./02-acd-patch-rungs-hex-substitution.md) |
| **BUG-02** | `convert_acd_to_l5x` hardcodes all data-table values to zero | [SPEC-04 (04-acd-datatable-value-extraction.md)](./04-acd-datatable-value-extraction.md) |
| **BUG-03** | `find_related_components` performs FAISS vector search, returning false-empty | [SPEC-01 (01-deterministic-ast-cross-reference.md)](./01-deterministic-ast-cross-reference.md) |
| **BUG-04** | `get_project_overview` returns unrelated project if target missing | [SPEC-11 (11-core-bugfixes-and-mcp-reliability.md)](./11-core-bugfixes-and-mcp-reliability.md) |
| **BUG-05** | Insecure `pickle.load()` on vector cache files | [SPEC-09 (09-security-safe-cache-and-deserialization.md)](./09-security-safe-cache-and-deserialization.md) |
| **BUG-06** | Unredirected `print()` to stdout corrupts JSON-RPC stdio framing | [SPEC-11 (11-core-bugfixes-and-mcp-reliability.md)](./11-core-bugfixes-and-mcp-reliability.md) |
| **BUG-07** | `generate_routine_export` hardcodes `<Program Name="MainProgram">` | [SPEC-11 (11-core-bugfixes-and-mcp-reliability.md)](./11-core-bugfixes-and-mcp-reliability.md) |
| **BUG-08** | Start/stop generator produces non-latching logic labeled "3-wire" | [SPEC-11 (11-core-bugfixes-and-mcp-reliability.md)](./11-core-bugfixes-and-mcp-reliability.md) |
| **BUG-09** | Syntax verifier warns `INPUT_ONLY` on valid timer/counter/math rungs | [SPEC-05 (05-plc-static-analysis-linter.md)](./05-plc-static-analysis-linter.md), [SPEC-11](./11-core-bugfixes-and-mcp-reliability.md) |
| **BUG-10** | Missing GitHub Actions CI workflow automation | [SPEC-10 (10-ci-and-build-infrastructure.md)](./10-ci-and-build-infrastructure.md) |

---

### 2. Ranked Feature Opportunities (§26)

| Rank | Feature Title | Spec Mapping |
| :---: | :--- | :--- |
| **1** | Deterministic AST Cross-Reference Engine | [SPEC-01](./01-deterministic-ast-cross-reference.md) |
| **2** | Direct ACD Comment Writer (`patch_comments`) | [SPEC-03](./03-direct-acd-comment-writer.md) |
| **3** | ACD Data-Table Value Extraction | [SPEC-04](./04-acd-datatable-value-extraction.md) |
| **4** | PLC Static Analysis Linter | [SPEC-05](./05-plc-static-analysis-linter.md) |
| **5** | Safe Modification Unified-Diff Staging Engine | [SPEC-06](./06-safe-modification-staging-diff.md) |
| **6** | Equipment Liveness Multi-Signal Classifier | [SPEC-07](./07-equipment-liveness-classifier.md) |
| **7** | SCADA I/O Coverage & Scaling Discrepancy Audit | [SPEC-08](./08-scada-ignition-export-coverage-and-scaling.md) |
| **8** | Automated GitHub Actions CI Pipeline | [SPEC-10](./10-ci-and-build-infrastructure.md) |

---

### 3. Top 25 Recommended Next Actions (§29)

| Action # | Subsystem & Task | Spec Mapping |
| :---: | :--- | :--- |
| **1** | Deterministic AST tag cross-reference (`find_tag_references`) | [SPEC-01](./01-deterministic-ast-cross-reference.md) |
| **2** | Fix `patch_rungs` `@HEX@` tag substitution | [SPEC-02](./02-acd-patch-rungs-hex-substitution.md) |
| **3** | Add GitHub Actions CI workflow | [SPEC-10](./10-ci-and-build-infrastructure.md) |
| **4** | Replace `pickle.load` with `safetensors`/JSON | [SPEC-09](./09-security-safe-cache-and-deserialization.md) |
| **5** | Close implemented issues in backlog | [SPEC-11](./11-core-bugfixes-and-mcp-reliability.md) |
| **6** | Fix `get_project_overview` wrong-project fallback | [SPEC-11](./11-core-bugfixes-and-mcp-reliability.md) |
| **7** | Redirect stray `print()` calls to `sys.stderr` | [SPEC-11](./11-core-bugfixes-and-mcp-reliability.md) |
| **8** | Unscaled analog alias fallback in Ignition exporter | [SPEC-08](./08-scada-ignition-export-coverage-and-scaling.md) |
| **9** | Replace naive 3-wire motor logic with latching seal-in branch | [SPEC-11](./11-core-bugfixes-and-mcp-reliability.md) |
| **10** | Fix `sdk_verifier_clean.py` false `INPUT_ONLY` warnings | [SPEC-05](./05-plc-static-analysis-linter.md), [SPEC-11](./11-core-bugfixes-and-mcp-reliability.md) |
| **11** | Unified-diff preview in `smart_insert_logic` | [SPEC-06](./06-safe-modification-staging-diff.md) |
| **12** | Direct ACD comment writer `patch_comments` | [SPEC-03](./03-direct-acd-comment-writer.md) |
| **13** | Remove fictitious `PRODUCE`/`CONSUME` instructions | [SPEC-11](./11-core-bugfixes-and-mcp-reliability.md) |
| **14** | Branch bracket `[` / `]` validation in ladder verifier | [SPEC-05](./05-plc-static-analysis-linter.md) |
| **15** | Duplicate destructive coil (`OTE`) static analysis check | [SPEC-05](./05-plc-static-analysis-linter.md) |
| **16** | Unreachable routine detector (uncalled via JSR) | [SPEC-05](./05-plc-static-analysis-linter.md) |
| **17** | Multi-signal equipment liveness classifier | [SPEC-07](./07-equipment-liveness-classifier.md) |
| **18** | ACD data-table byte decoder | [SPEC-04](./04-acd-datatable-value-extraction.md) |
| **19** | Python 3.12 runtime version guard | [SPEC-11](./11-core-bugfixes-and-mcp-reliability.md) |
| **20** | Target `Program` context in `generate_routine_export` | [SPEC-11](./11-core-bugfixes-and-mcp-reliability.md) |
| **21** | Human-readable Ignition naming engine (`gen.py`) | [SPEC-08](./08-scada-ignition-export-coverage-and-scaling.md) |
| **22** | HTML visualization report for Ignition tag export diffs | [SPEC-08](./08-scada-ignition-export-coverage-and-scaling.md) |
| **23** | SCADA I/O coverage audit tool | [SPEC-08](./08-scada-ignition-export-coverage-and-scaling.md) |
| **24** | Version-tagged instruction documentation search | [SPEC-12](./12-documentation-and-drawings-enhancement.md) |
| **25** | Vector cache cleanup / invalidation CLI tool | [SPEC-09](./09-security-safe-cache-and-deserialization.md) |
