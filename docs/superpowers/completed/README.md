# Completed and archived design documents

Moved here on 2026-09-18 after an implementation audit against `main`.
These are historical records; the code and tests are the source of truth.
Open follow-ups from these documents are listed in `../ROADMAP.md` §6.

| Document | Outcome | Evidence |
| :--- | :--- | :--- |
| `2026-08-04-vendor-acd-in-repo.md` | Complete | `src/acd/`, `tests/test_acd_vendoring.py` |
| `2026-08-04-acd-l5x-fidelity-v38.md` + `-design.md` | Complete (code); doc checkboxes were never ticked | `tests/test_acd_l5x_fidelity.py`, `src/l5x_analyzer/l5x_semantic_validation.py` |
| `2026-08-05-iterative-comment-analysis-plan.md` + `-design.md` | Complete; hardening tracked in #15 | `src/comment_graph/`, 110 tests in `tests/comment_graph/` |
| `2026-08-05-bug-tracker-roadmap-design.md` | Superseded by GitHub Issues on 2026-08-10 | `.github/ISSUE_TEMPLATE/` is the only surviving deliverable |
| `2026-08-10-human-ignition-naming-engine.md` + `-design.md` | Complete; merged to main 2026-09-18 (#29) | `src/ignition_exporter/naming_engine.py`, `tests/ignition_exporter/test_naming_engine.py` |
| `HANDOFF-human-ignition-naming-engine.md` | Handoff note for the above; branch and worktree since deleted | — |
