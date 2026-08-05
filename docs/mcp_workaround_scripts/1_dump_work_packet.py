# -*- coding: utf-8 -*-
"""
STEP 1 of the comment-authoring workaround.

Purpose: turn the orchestrator's work_packet.json into dense, per-routine text
dumps that are readable in one pass, so the ladder logic behind each escalated
operand/tag can be reasoned about without paging through a 1,500-line JSON blob.

Why this exists: `generate_program_comments` returns a work packet whose
`to_resolve` list (209 items here) is too large to review inline. It writes the
full list to work_packet.json on disk, but as raw nested JSON. This flattens it.

Input : <deliverables>/work_packet.json   (written by generate_program_comments)
Output: ./dumps/dump_<Routine>.txt         (one file per routine + NO_EVIDENCE)

Run with any Python 3.8+ (no third-party deps).
"""
import json
import os
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
DELIVERABLES = os.path.dirname(HERE)                      # parent = deliverables dir
WP = os.path.join(DELIVERABLES, "work_packet.json")
OUT_DIR = os.path.join(HERE, "dumps")


def main():
    with open(WP, encoding="utf-8") as fh:
        d = json.load(fh)
    to_resolve = d["to_resolve"]

    os.makedirs(OUT_DIR, exist_ok=True)

    # group each item under the routine of its first rung reference
    groups = collections.OrderedDict()
    for it in to_resolve:
        rr = it.get("rung_references", [])
        routine = rr[0]["routine"] if rr else "NO_EVIDENCE"
        groups.setdefault(routine, []).append(it)

    for routine, items in groups.items():
        path = os.path.join(OUT_DIR, "dump_%s.txt" % routine)
        with open(path, "w", encoding="utf-8") as f:
            f.write("ROUTINE: %s  (%d items)\n" % (routine, len(items)))
            for it in items:
                dd = it["draft_decision"]
                f.write("\n=== %s  [TYPE=%s SCOPE=%s occ=%s]\n"
                        % (dd["NAME"], dd["TYPE"], dd["SCOPE"], it.get("occurrence_count", 0)))
                for r in it.get("rung_references", []):
                    f.write("  R%s @%s: %s\n"
                            % (r["rung_number"], r["routine"], r["ladder_logic"].strip()))
                    rc = (r.get("rung_comment") or "").strip()
                    if rc:
                        f.write("     ; %s\n" % rc)
                    adj = r.get("adjacent_tags")
                    if adj:
                        f.write("     adj: %s\n" % adj)
        print("wrote", path, len(items), "items")


if __name__ == "__main__":
    main()
