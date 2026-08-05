# Feature Roadmap

Planned work for the Studio 5000 AI Assistant, grouped by horizon. Hand-edited, in-tree.

**Legend**
- **ID:** `FEAT-NNN`, assigned sequentially, never reused.
- **Bucket:** `Now` (active / next up) · `Next` (queued) · `Later` (someday / lower priority).
- **Priority:** `High` · `Medium` · `Low`.
- **Resolves:** the [BUG](BUGS.md) IDs this feature would close, if any.
- SDK-interface (`src/sdk_interface`) work is out of scope — the live SDK is gated off by default and offline work targets the vendored `src/acd` parser.

## Summary

### Now
| ID | Priority | Summary | Resolves |
|----|----------|---------|----------|
| [FEAT-001](#feat-001--proper-rll-xml-generation) | High | Proper RLL XML generation (replace raw-text-in-CDATA output) | BUG-001 |
| [FEAT-002](#feat-002--analyze_comment_graph-convergence-tuning) | High | `analyze_comment_graph` convergence tuning & hardening | — |
| [FEAT-003](#feat-003--v38-l5x--acd-parity) | High | v38 L5X / ACD parity for the vendored offline parser/exporter | — |

### Next
| ID | Priority | Summary | Resolves |
|----|----------|---------|----------|
| [FEAT-004](#feat-004--structured-text-st--function-block-fbd-generation) | Medium | Structured Text (ST) + Function Block (FBD) generation | BUG-002 |
| [FEAT-005](#feat-005--advanced--static-validation) | Medium | Advanced / static validation & best-practices checking | — |

### Later
| ID | Priority | Summary | Resolves |
|----|----------|---------|----------|
| [FEAT-006](#feat-006--multiple-studio-5000-version-detection) | Low | Multiple Studio 5000 version detection & compatibility | — |
| [FEAT-007](#feat-007--factorytalk-view--rslinx-integration) | Low | Integration with FactoryTalk View / RSLinx | — |
| [FEAT-008](#feat-008--cloudweb-team-interface) | Low | Cloud/web interface for team collaboration | — |

## Details

### FEAT-001 — Proper RLL XML generation
- **Bucket:** Now · **Priority:** High · **Resolves:** BUG-001
- **Source:** README.md:993
- **Outcome:** Emit well-formed RLL XML for generated ladder logic instead of raw text in CDATA, so generated L5X imports into Studio 5000 without manual formatting fixes.

### FEAT-002 — `analyze_comment_graph` convergence tuning
- **Bucket:** Now · **Priority:** High · **Resolves:** —
- **Source:** src/comment_graph/, docs/superpowers/plans/2026-08-05-iterative-comment-analysis-plan.md
- **Outcome:** Tune and harden the iterative comment-analysis engine — convergence behavior, placeholder/seed filtering, and scheduler robustness — so proposals stabilize predictably on real projects.

### FEAT-003 — v38 L5X / ACD parity
- **Bucket:** Now · **Priority:** High · **Resolves:** —
- **Source:** Recent commits (f7cd63b "PLC: add v38 offline ACD parity workflow")
- **Outcome:** Bring the vendored offline ACD parser/exporter to full parity with Studio 5000 v38 L5X semantics for round-trip fidelity.

### FEAT-004 — Structured Text (ST) + Function Block (FBD) generation
- **Bucket:** Next · **Priority:** Medium · **Resolves:** BUG-002
- **Source:** README.md:1007
- **Outcome:** Extend generation beyond ladder to ST and FBD, replacing the current "not implemented" placeholder path.

### FEAT-005 — Advanced / static validation
- **Bucket:** Next · **Priority:** Medium · **Resolves:** —
- **Source:** README.md:1010
- **Outcome:** Add static analysis and best-practices checking on top of the existing fast syntax/instruction validation.

### FEAT-006 — Multiple Studio 5000 version detection
- **Bucket:** Later · **Priority:** Low · **Resolves:** —
- **Source:** README.md:1013
- **Outcome:** Dynamically detect the installed Studio 5000 version and adapt documentation roots / L5X targets for compatibility across major revisions.

### FEAT-007 — FactoryTalk View / RSLinx integration
- **Bucket:** Later · **Priority:** Low · **Resolves:** —
- **Source:** README.md:1014
- **Outcome:** Extend beyond Logix Designer to related Rockwell tools (FactoryTalk View, RSLinx) for broader system context.

### FEAT-008 — Cloud/web team interface
- **Bucket:** Later · **Priority:** Low · **Resolves:** —
- **Source:** README.md:1015
- **Outcome:** Provide a web-based interface for team collaboration over the assistant's capabilities.
