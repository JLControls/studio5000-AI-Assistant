#!/usr/bin/env python3
"""
PLC Comment Pipeline

Provides automated context extraction, ladder reasoning payload generation,
HTML audit report generation, CSV delta export, and granular incremental memory
tracking for Rockwell Studio 5000 / Logix projects.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

try:
    from ..ladder_renderer import LADDER_RENDERER_CSS, LADDER_RENDERER_JS, render_visual_rung_html
except ImportError:
    try:
        from ladder_renderer import LADDER_RENDERER_CSS, LADDER_RENDERER_JS, render_visual_rung_html
    except ImportError:
        LADDER_RENDERER_CSS = ""
        LADDER_RENDERER_JS = ""
        def render_visual_rung_html(rung_text, rung_number=0, comment="", tag_descriptions=None, unique_id="rung_0"):
            return f'<div class="code-block">{rung_text}</div>'


class PLCCommentPipeline:
    """Core engine for PLC tag/comment analysis, deliverable generation, and memory caching."""

    @staticmethod
    def resolve_l5x_path(file_path: str | Path) -> Path:
        """Resolve an ACD or L5X file path to an accessible L5X file."""
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if path.suffix.lower() == ".l5x":
            return path

        if path.suffix.lower() == ".acd":
            # Check for existing L5X exports in same directory
            candidates = [
                path.with_suffix(".L5X"),
                path.with_name(f"{path.stem}.Offline.L5X"),
                path.with_name(f"{path.stem}.L5X"),
            ]
            for candidate in candidates:
                if candidate.exists():
                    logger.info(f"Resolved ACD {path.name} to existing export {candidate.name}")
                    return candidate

            # Auto-convert ACD to L5X if no existing export found (P8 fix)
            try:
                from l5x_analyzer.acd_offline_convert import convert_acd_to_l5x
                target_l5x = path.with_name(f"{path.stem}.Offline.L5X")
                logger.info(f"Auto-converting ACD {path.name} to {target_l5x.name}")
                res = convert_acd_to_l5x(str(path), str(target_l5x), generate_report=False)
                if target_l5x.exists():
                    return target_l5x
            except Exception as exc:
                logger.warning(f"Failed to auto-convert ACD to L5X: {exc}")

            raise FileNotFoundError(
                f"No associated L5X export found for ACD file: {path}. "
                f"Export to L5X first using convert_acd_to_l5x."
            )

        raise ValueError(f"Unsupported file format: {path.suffix}")

    @staticmethod
    def parse_l5x_tree(l5x_path: Path) -> ET.ElementTree:
        """Parse L5X XML file handling UTF-8 or BOM encodings cleanly."""
        raw = l5x_path.read_bytes()
        # Strip UTF-8 BOM if present
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return ET.fromstring(raw.decode("utf-8", errors="replace"))

    def get_uncommented_tags(self, file_path: str | Path, scope_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Scan L5X for tags missing comments or containing placeholder descriptions.

        Returns:
            Dict with total_tags, uncommented_tags_count, and list of uncommented_tags dicts.
        """
        l5x_path = self.resolve_l5x_path(file_path)
        root = self.parse_l5x_tree(l5x_path)

        uncommented = []
        total_tags = 0

        # Helper to process a <Tags> container
        def _process_tags_node(tags_node: ET.Element, scope_name: str):
            nonlocal total_tags
            for tag in tags_node.findall("Tag"):
                total_tags += 1
                tag_name = tag.attrib.get("Name", "")
                data_type = tag.attrib.get("DataType", "")
                alias_for = tag.attrib.get("AliasFor", "")

                comment_elem = tag.find("Comment")
                description = comment_elem.text.strip() if (comment_elem is not None and comment_elem.text) else ""

                # Check operand comments if array/struct
                operand_comments = []
                comments_elem = tag.find("Comments")
                if comments_elem is not None:
                    for op_c in comments_elem.findall("Comment"):
                        op_str = op_c.attrib.get("Operand", "")
                        op_text = op_c.text.strip() if op_c.text else ""
                        if op_text:
                            operand_comments.append({"operand": op_str, "description": op_text})

                is_missing = not description and not operand_comments
                if is_missing:
                    uncommented.append({
                        "name": tag_name,
                        "scope": scope_name,
                        "data_type": data_type,
                        "alias_for": alias_for,
                        "has_comment": False,
                    })

        # Controller Scope Tags
        controller_elem = root.find("Controller")
        controller_name = controller_elem.attrib.get("Name", "Controller") if controller_elem is not None else "Controller"
        
        # Check if scope_filter matches a routine name
        routine_matched_tags = None
        if scope_filter:
            for routine in root.findall(".//Routine"):
                r_name = routine.attrib.get("Name", "")
                if scope_filter.lower() == r_name.lower():
                    # Collect all text from rungs in this routine
                    routine_matched_tags = set()
                    for rung in routine.findall(".//Rung"):
                        text_elem = rung.find("Text")
                        if text_elem is not None and text_elem.text:
                            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text_elem.text):
                                routine_matched_tags.add(token)
                    break

        if not scope_filter or scope_filter.lower() == "controller" or routine_matched_tags is not None:
            ctrl_tags = root.find(".//Controller/Tags")
            if ctrl_tags is not None:
                _process_tags_node(ctrl_tags, "Controller")

        # Program Scope Tags
        programs_elem = root.find(".//Programs")
        if programs_elem is not None:
            for prog in programs_elem.findall("Program"):
                prog_name = prog.attrib.get("Name", "")
                if scope_filter and scope_filter.lower() not in (prog_name.lower(), "program") and routine_matched_tags is None:
                    continue
                prog_tags = prog.find("Tags")
                if prog_tags is not None:
                    _process_tags_node(prog_tags, prog_name)

        if routine_matched_tags is not None:
            uncommented = [t for t in uncommented if t["name"] in routine_matched_tags]

        return {
            "l5x_file": str(l5x_path),
            "project_name": controller_name,
            "total_tags_scanned": total_tags,
            "uncommented_tags_count": len(uncommented),
            "uncommented_tags": uncommented,
        }

    def get_tag_reasoning_context(self, tag_name: str, file_path: str | Path) -> Dict[str, Any]:
        """
        Extract rich context for a target tag: definitions, rungs referencing it,
        ladder logic text, rung comments, and adjacent tags with descriptions.
        """
        l5x_path = self.resolve_l5x_path(file_path)
        root = self.parse_l5x_tree(l5x_path)

        # 1. Build a master map of all known tag descriptions for adjacent lookup
        tag_desc_map: Dict[str, str] = {}
        for tag in root.findall(".//Tag"):
            name = tag.attrib.get("Name", "")
            c = tag.find("Comment")
            if name and c is not None and c.text:
                tag_desc_map[name] = c.text.strip()

        # 2. Find target tag definition
        tag_def = None
        for tag in root.findall(".//Tag"):
            if tag.attrib.get("Name") == tag_name:
                c = tag.find("Comment")
                tag_def = {
                    "name": tag_name,
                    "scope": "Controller" if tag in root.findall(".//Controller/Tags/Tag") else "Program",
                    "data_type": tag.attrib.get("DataType", ""),
                    "alias_for": tag.attrib.get("AliasFor", ""),
                    "current_comment": c.text.strip() if (c is not None and c.text) else "",
                }
                break

        # 3. Scan all routines for rung occurrences (P5: identifier-safe boundaries for array operands)
        word_pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(tag_name) + r"(?![A-Za-z0-9_:\.\[\]])")
        identifier_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_:\.\[\]]*")

        rung_references = []

        for program in root.findall(".//Programs/Program"):
            prog_name = program.attrib.get("Name", "MainProgram")
            for routine in program.findall(".//Routine"):
                rout_name = routine.attrib.get("Name", "")
                rll = routine.find("RLLContent")
                if rll is None:
                    continue

                for rung in rll.findall("Rung"):
                    rung_num = rung.attrib.get("Number", "")
                    text_elem = rung.find("Text")
                    rung_text = text_elem.text.strip() if (text_elem is not None and text_elem.text) else ""

                    if not word_pattern.search(rung_text):
                        continue

                    comment_elem = rung.find("Comment")
                    rung_comment = comment_elem.text.strip() if (comment_elem is not None and comment_elem.text) else ""

                    # Find adjacent tags in same rung
                    tokens = identifier_pattern.findall(rung_text)
                    adjacent_tags = []
                    seen_tokens = set()
                    for token in tokens:
                        # Extract base tag name before punctuation/indices
                        base_token = token.split(".")[0].split("[")[0]
                        if base_token != tag_name and base_token not in seen_tokens and len(base_token) > 1:
                            seen_tokens.add(base_token)
                            adjacent_tags.append({
                                "name": token,
                                "description": tag_desc_map.get(base_token, tag_desc_map.get(token, "")),
                            })

                    rung_references.append({
                        "program": prog_name,
                        "routine": rout_name,
                        "rung_number": rung_num,
                        "ladder_logic": rung_text,
                        "rung_comment": rung_comment,
                        "adjacent_tags": adjacent_tags,
                    })

        return {
            "tag_name": tag_name,
            "tag_definition": tag_def or {"name": tag_name, "status": "Not defined in Tag table"},
            "occurrence_count": len(rung_references),
            "rung_references": rung_references,
        }

    def generate_deliverables(
        self,
        decisions: Optional[List[Dict[str, Any]]] = None,
        output_dir: str | Path | None = None,
        project_name: str | None = None,
        file_path: str | Path | None = None,
        edit_acd: bool = False,
        target_acd: str | Path | None = None,
        decisions_path: str | Path | None = None,
        work_packet_path: str | Path | None = None,
    ) -> Dict[str, Any]:
        """
        Generate Studio 5000 deliverables (Comment_Delta.CSV, comment_review_report.html,
        and optionally an updated .ACD project file when direct ACD editing is requested).

        Accepts decisions inline via `decisions`, or from disk via `decisions_path` or `work_packet_path`.
        Deliverables default to a directory located at the same level as the target file.
        """
        # 0. Resolve decisions input source (P1, P2)
        provided_sources = sum(x is not None for x in (decisions, decisions_path, work_packet_path))
        if provided_sources != 1:
            raise ValueError("Must provide exactly one of: decisions, decisions_path, or work_packet_path")

        skipped_unauthored_drafts = 0
        if decisions_path:
            p_dec = Path(decisions_path).resolve()
            if not p_dec.exists():
                raise FileNotFoundError(f"decisions_path file not found: {p_dec}")
            decisions = json.loads(p_dec.read_text(encoding="utf-8"))
        elif work_packet_path:
            p_pkt = Path(work_packet_path).resolve()
            if not p_pkt.exists():
                raise FileNotFoundError(f"work_packet_path file not found: {p_pkt}")
            packet = json.loads(p_pkt.read_text(encoding="utf-8"))
            auto_decisions = packet.get("auto_decisions") or []
            to_resolve = packet.get("to_resolve") or []
            authored_drafts = []
            for item in to_resolve:
                draft = item.get("draft_decision") or {}
                desc = (draft.get("PROPOSED_DESCRIPTION") or "").strip()
                if desc:
                    authored_drafts.append(draft)
                else:
                    skipped_unauthored_drafts += 1
            decisions = auto_decisions + authored_drafts
            if not file_path and not target_acd:
                # Infer reference location from packet or work_packet directory
                file_path = p_pkt.parent

        # Determine reference file path (to place deliverables folder at the same level)
        ref_file = None
        if target_acd:
            ref_file = Path(target_acd).resolve()
        elif file_path:
            ref_file = Path(file_path).resolve()

        # Derive the project name from the target artifact rather than hardcoding.
        if not project_name:
            project_name = ref_file.stem if ref_file else "PLC_Project"

        if output_dir:
            out_p = Path(output_dir)
            if out_p.is_absolute() or not ref_file:
                out_path = out_p.resolve()
            else:
                out_path = (ref_file.parent / out_p).resolve()
        elif ref_file:
            out_path = ref_file.parent / f"{ref_file.stem}_deliverables"
        else:
            out_path = Path("deliverables").resolve()

        out_path.mkdir(parents=True, exist_ok=True)

        csv_path = out_path / "Comment_Delta.CSV"
        html_path = out_path / "comment_review_report.html"

        # 1. Generate Studio 5000 Import Delta CSV (cp1252, CRLF, $N)
        prefix_lines = [
            'remark,"CSV-Import-Export"\r\n',
            'remark,"Export created by AI PLC Comment Pipeline"\r\n',
            '0.3\r\n',
        ]
        headers = ["TYPE", "SCOPE", "NAME", "DESCRIPTION", "DATATYPE", "SPECIFIER", "ATTRIBUTES"]

        def _normalize_cp1252(text: str) -> str:
            if not text:
                return ""
            replacements = {
                "→": "->", "←": "<-", "≥": ">=", "≤": "<=",
                "–": "-", "—": "-", "°": "deg", "µ": "u", "″": '"', "′": "'",
            }
            for k, v in replacements.items():
                text = text.replace(k, v)
            return text

        csv_rows = []
        for dec in decisions:
            rec_type = dec.get("TYPE", "COMMENT")
            scope = _normalize_cp1252(dec.get("SCOPE", ""))
            name = dec.get("NAME", "")
            raw_desc = _normalize_cp1252(dec.get("PROPOSED_DESCRIPTION", ""))
            # Convert python newline to literal $N for Studio 5000 CSV
            formatted_desc = raw_desc.replace("\r\n", "$N").replace("\n", "$N")

            # Studio 5000 operand comments are COMMENT rows whose member/operand
            # reference lives in the SPECIFIER column (col 6); tag/component
            # descriptions are TAG rows carrying DATATYPE/ATTRIBUTES instead.
            datatype = _normalize_cp1252(dec.get("DATATYPE", ""))
            specifier = _normalize_cp1252(dec.get("SPECIFIER", ""))
            attributes = _normalize_cp1252(dec.get("ATTRIBUTES", ""))

            # P7: Split NAME into base tag + SPECIFIER for COMMENT rows if specifier is missing
            if rec_type == "COMMENT" and not specifier and ("[" in name or "." in name):
                m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)(.*)$", name)
                if m:
                    name = m.group(1)
                    specifier = m.group(2)

            csv_rows.append([rec_type, scope, name, formatted_desc, datatype, specifier, attributes])

        with csv_path.open("w", encoding="cp1252", errors="replace", newline="") as f:
            f.writelines(prefix_lines)
            writer = csv.writer(f, lineterminator="\r\n")
            writer.writerow(headers)
            writer.writerows(csv_rows)

        # 2. Generate Interactive HTML Review Report
        html_content = self._render_html_report(project_name, decisions)
        html_path.write_text(html_content, encoding="utf-8")

        # 3. Persist the exact decision set used (reproducibility / hand-off).
        decisions_json_path = out_path / "decisions.json"
        decisions_json_path.write_text(json.dumps(decisions, indent=2), encoding="utf-8")

        res: Dict[str, Any] = {
            "csv_delta": str(csv_path),
            "html_report": str(html_path),
            "decisions_json": str(decisions_json_path),
            "decisions_processed": len(decisions),
            "skipped_unauthored_drafts": skipped_unauthored_drafts,
        }

        # 4. Emit object-level comment memory alongside the deliverables so the
        # full artifact set (CSV + HTML + decisions.json + comment_memory.json)
        # is produced by a single call. Requires an L5X/ACD to hash routines.
        mem_source = target_acd or file_path
        if mem_source:
            try:
                mem = self.manage_incremental_memory(
                    mem_source, out_path / "comment_memory.json", decisions
                )
                res["comment_memory"] = mem.get("memory_file")
            except Exception as exc:  # non-fatal: deliverables still valid
                logger.warning(f"comment_memory.json not written: {exc}")
                res["comment_memory_error"] = str(exc)

        # 3. Direct ACD editing (if requested)
        if edit_acd or target_acd:
            acd_target = None
            if target_acd:
                cand = Path(target_acd).resolve()
                if cand.exists():
                    acd_target = cand
            elif ref_file:
                if ref_file.suffix.lower() == ".acd":
                    acd_target = ref_file
                else:
                    for cand_ext in [".ACD", ".acd"]:
                        cand = ref_file.with_suffix(cand_ext)
                        if cand.exists():
                            acd_target = cand
                            break

            if acd_target and acd_target.exists():
                try:
                    from acd.api import load_acd, patch_rungs, save_acd
                    proj = load_acd(str(acd_target))
                    changes: Dict[int, str] = {}

                    if hasattr(proj, "controller") and hasattr(proj.controller, "programs"):
                        for prog in proj.controller.programs:
                            for rout in prog.routines:
                                rung_ids = getattr(rout, "_rung_ids", [])
                                for idx, rung_text in enumerate(rout.rungs):
                                    if idx < len(rung_ids):
                                        oid = rung_ids[idx]
                                        matched_text = None
                                        for dec in decisions:
                                            d_rout = dec.get("SCOPE") or dec.get("routine")
                                            d_rung = dec.get("rung_number")
                                            if (
                                                d_rout
                                                and str(d_rout).lower() == rout.name.lower()
                                                and d_rung is not None
                                                and str(d_rung) == str(idx)
                                                and dec.get("PROPOSED_RUNG_TEXT")
                                            ):
                                                matched_text = dec["PROPOSED_RUNG_TEXT"]
                                                break
                                        if matched_text:
                                            changes[oid] = matched_text

                    if changes:
                        patch_rungs(proj, changes)

                    updated_acd_name = f"{acd_target.stem}_updated.ACD"
                    updated_acd_path = out_path / updated_acd_name
                    save_acd(proj, str(updated_acd_path))
                    res["updated_acd"] = str(updated_acd_path)
                except Exception as exc:
                    logger.error(f"Failed direct ACD edit: {exc}")
                    res["updated_acd_error"] = str(exc)
            else:
                res["updated_acd_error"] = f"No target ACD file found for direct editing (ref: {ref_file})"

        return res

    @staticmethod
    def parse_rung_structure(snippet: str) -> Dict[str, Any]:
        """Parse RLL snippet into parallel OR branches or sequential AND conditions."""
        instr_pattern = re.compile(r"([A-Z0-9_]+)\s*\(([^)]+)\)")
        output_instrs = ["OTE", "OTL", "OTU", "MOV", "COP", "ADD", "SUB", "MUL", "DIV"]
        
        all_matches = instr_pattern.findall(snippet)
        cond_matches = []
        out_matches = []
        
        for instr, op_str in all_matches:
            if instr in output_instrs:
                out_matches.append((instr, op_str))
            else:
                cond_matches.append((instr, op_str))

        snippet_clean = snippet.strip()
        if snippet_clean.startswith("[") and "]" in snippet_clean:
            b_content = snippet_clean[1:snippet_clean.rfind("]")]
            if "," in b_content:
                branches_raw = b_content.split(",")
                branches = []
                for b in branches_raw:
                    b_instrs = [m for m in instr_pattern.findall(b) if m[0] not in output_instrs]
                    if b_instrs:
                        branches.append(b_instrs)
                if len(branches) > 1:
                    return {"type": "OR", "branches": branches, "outputs": out_matches}
        return {"type": "AND", "inputs": cond_matches, "outputs": out_matches}

    @staticmethod
    def build_mermaid_flow(dec: Dict[str, Any], tag_descs: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Generate clean Mermaid flowchart with permanently attached True and False output ports on every decision block."""
        tag_descs = tag_descs or {}
        target_tag = dec.get("NAME", "TargetTag")
        snippet = dec.get("LOGIC_SNIPPET", "")

        def sanitize(name: str) -> str:
            return re.sub(r"[^a-zA-Z0-9_]", "_", name)

        def escape_mermaid(text: str) -> str:
            if not text:
                return ""
            text = str(text).replace('"', "&quot;").replace("'", "&#39;")
            text = text.replace("[", "&#91;").replace("]", "&#93;")
            text = text.replace("(", "&#40;").replace(")", "&#41;")
            return text

        target_desc = tag_descs.get(target_tag, dec.get("PROPOSED_DESCRIPTION", "Target Tag"))
        target_desc_esc = escape_mermaid(target_desc)
        target_tag_esc = escape_mermaid(target_tag)

        struct = PLCCommentPipeline.parse_rung_structure(snippet)

        lines = ["flowchart LR"]
        lines.append("    classDef targetStyle fill:#0284c7,stroke:#38bdf8,stroke-width:2px,color:#ffffff,font-weight:bold;")
        lines.append("    classDef condStyle fill:#1e293b,stroke:#64748b,stroke-width:2px,color:#f8fafc;")
        lines.append("    classDef actionStyle fill:#065f46,stroke:#34d399,stroke-width:2px,color:#ffffff,font-weight:bold;")

        lines.append('    Start(["Start Evaluation"])')

        link_idx = 0
        link_styles = []

        LINE_THICKNESS = "2px"
        COLOR_ACTIVE = "#22c55e"       # Green
        COLOR_INACTIVE = "#ef4444"     # Complimentary Red

        # Output node
        outputs = struct.get("outputs", [])
        if outputs:
            instr, op_str = outputs[0]
            op = op_str.split(",")[0].strip()
            op_clean = sanitize(op)
            op_desc = tag_descs.get(op, target_desc)
            op_esc = escape_mermaid(op)
            op_desc_esc = escape_mermaid(op_desc)
            is_target = (op == target_tag or op.startswith(target_tag))

            out_id = f"Out_0_{op_clean}"
            action_text = f"<div title='{op_esc}' class='out-node'><b>{instr}</b><br/><i>{op_desc_esc}</i></div>"
            lines.append(f'    {out_id}[["{action_text}"]]:::{"targetStyle" if is_target else "actionStyle"}')
        else:
            out_id = f"Out_0_{sanitize(target_tag)}"
            out_text = f"<div title='{target_tag_esc}' class='out-node'><i>{target_desc_esc}</i></div>"
            lines.append(f'    {out_id}[["{out_text}"]]:::targetStyle')

        if struct["type"] == "OR":
            branches = struct["branches"]
            prev_start = "Start"

            for b_idx, branch in enumerate(branches):
                b_prev = prev_start
                for idx, (instr, op_str) in enumerate(branch):
                    op = op_str.split(",")[0].strip()
                    op_clean = sanitize(op)
                    op_desc = tag_descs.get(op, op)
                    op_esc = escape_mermaid(op)
                    op_desc_esc = escape_mermaid(op_desc)
                    is_target = (op == target_tag or op.startswith(target_tag))

                    node_id = f"Cond_{b_idx}_{idx}_{op_clean}"
                    cond_html = (
                        f"<table style='border-collapse:collapse;width:100%;margin:0;padding:0;' title='{op_esc}'>"
                        f"<tr>"
                        f"<td style='padding:6px 10px;font-size:11px;font-weight:600;color:#f8fafc;text-align:center;vertical-align:middle;'>{op_desc_esc}</td>"
                        f"<td style='border-left:1px solid rgba(255,255,255,0.25);padding:0;width:44px;vertical-align:middle;'>"
                        f"<div style='background-color:#064e3b;color:#4ade80;border-bottom:1px solid rgba(255,255,255,0.25);font-size:9px;font-weight:800;padding:4px 2px;text-align:center;letter-spacing:0.5px;'>TRUE</div>"
                        f"<div style='background-color:#7f1d1d;color:#fca5a5;font-size:9px;font-weight:800;padding:4px 2px;text-align:center;letter-spacing:0.5px;'>FALSE</div>"
                        f"</td>"
                        f"</tr>"
                        f"</table>"
                    )

                    lines.append(f'    {node_id}["{cond_html}"]:::{"targetStyle" if is_target else "condStyle"}')

                    # Link into this block from previous node
                    if idx == 0:
                        if b_idx == 0:
                            lines.append(f"    {b_prev} --> {node_id}")
                            link_styles.append(f"linkStyle {link_idx} stroke:{COLOR_ACTIVE},stroke-width:{LINE_THICKNESS},fill:none;")
                            link_idx += 1
                        else:
                            lines.append(f"    {b_prev} --> {node_id}")
                            link_styles.append(f"linkStyle {link_idx} stroke:{COLOR_INACTIVE},stroke-width:{LINE_THICKNESS},fill:none;")
                            link_idx += 1
                    else:
                        lines.append(f"    {b_prev} --> {node_id}")
                        link_styles.append(f"linkStyle {link_idx} stroke:{COLOR_ACTIVE},stroke-width:{LINE_THICKNESS},fill:none;")
                        link_idx += 1

                    # If last node in branch, leading to Output
                    if idx == len(branch) - 1:
                        lines.append(f"    {node_id} --> {out_id}")
                        link_styles.append(f"linkStyle {link_idx} stroke:{COLOR_ACTIVE},stroke-width:{LINE_THICKNESS},fill:none;")
                        link_idx += 1

                    if idx == 0 and b_idx < len(branches) - 1:
                        b_prev = node_id
                    else:
                        b_prev = node_id
        else:
            inputs = struct["inputs"]
            prev_node = "Start"
            for idx, (instr, op_str) in enumerate(inputs):
                op = op_str.split(",")[0].strip()
                op_clean = sanitize(op)
                op_desc = tag_descs.get(op, op)
                op_esc = escape_mermaid(op)
                op_desc_esc = escape_mermaid(op_desc)
                is_target = (op == target_tag or op.startswith(target_tag))

                node_id = f"Cond_{idx}_{op_clean}"
                cond_html = (
                    f"<table style='border-collapse:collapse;width:100%;margin:0;padding:0;' title='{op_esc}'>"
                    f"<tr>"
                    f"<td style='padding:6px 10px;font-size:11px;font-weight:600;color:#f8fafc;text-align:center;vertical-align:middle;'>{op_desc_esc}</td>"
                    f"<td style='border-left:1px solid rgba(255,255,255,0.25);padding:0;width:44px;vertical-align:middle;'>"
                    f"<div style='background-color:#064e3b;color:#4ade80;border-bottom:1px solid rgba(255,255,255,0.25);font-size:9px;font-weight:800;padding:4px 2px;text-align:center;letter-spacing:0.5px;'>TRUE</div>"
                    f"<div style='background-color:#7f1d1d;color:#fca5a5;font-size:9px;font-weight:800;padding:4px 2px;text-align:center;letter-spacing:0.5px;'>FALSE</div>"
                    f"</td>"
                    f"</tr>"
                    f"</table>"
                )

                lines.append(f'    {node_id}["{cond_html}"]:::{"targetStyle" if is_target else "condStyle"}')

                lines.append(f"    {prev_node} --> {node_id}")
                link_styles.append(f"linkStyle {link_idx} stroke:{COLOR_ACTIVE},stroke-width:{LINE_THICKNESS},fill:none;")
                link_idx += 1

                prev_node = node_id

            lines.append(f"    {prev_node} --> {out_id}")
            link_styles.append(f"linkStyle {link_idx} stroke:{COLOR_ACTIVE},stroke-width:{LINE_THICKNESS},fill:none;")
            link_idx += 1

        lines.extend(link_styles)
        full_code = "\n".join(lines)
        return {"all": full_code, "inputs": full_code, "outputs": full_code}

    def _render_html_report(self, project_name: str, decisions: List[Dict[str, Any]]) -> str:
        """Render standalone HTML dashboard for engineer review with common signal flow list and interactive rendering."""
        high_conf = sum(1 for d in decisions if d.get("CONFIDENCE", "").upper() == "HIGH")
        med_conf = sum(1 for d in decisions if d.get("CONFIDENCE", "").upper() == "MEDIUM")
        low_conf = sum(1 for d in decisions if d.get("CONFIDENCE", "").upper() == "LOW")

        cards_html = []
        tag_descriptions = {d.get("NAME", ""): d.get("PROPOSED_DESCRIPTION", "") for d in decisions if d.get("NAME")}
        for idx, dec in enumerate(decisions):
            conf = dec.get("CONFIDENCE", "MEDIUM").upper()
            badge_class = "badge-high" if conf == "HIGH" else "badge-med" if conf == "MEDIUM" else "badge-low"

            tag_name = dec.get("NAME", "Tag")
            rung_refs = dec.get("RUNG_REFERENCES", [])

            # Fallback if no rung_references array attached
            if not rung_refs:
                logic_snippet = dec.get("LOGIC_SNIPPET", "")
                rung_refs = [{
                    "routine": dec.get("SCOPE", "Routine"),
                    "rung_number": 0,
                    "direction": "Driver (Output)",
                    "is_output": True,
                    "ladder_logic": logic_snippet,
                    "rung_comment": dec.get("RATIONALE", ""),
                }]

            driver_count = sum(1 for r in rung_refs if r.get("is_output"))
            driven_count = sum(1 for r in rung_refs if not r.get("is_output"))

            sidebar_items_html = []
            render_items_html = []

            for f_idx, r_ref in enumerate(rung_refs):
                is_out = r_ref.get("is_output", False)
                item_type = "driver" if is_out else "driven"
                badge_lbl = "🟢 Driver" if is_out else "🟠 Driven"
                badge_cls = "badge-driver" if is_out else "badge-driven"

                rout_name = r_ref.get("routine", "Routine")
                rung_num = r_ref.get("rung_number", 0)
                logic_text = r_ref.get("ladder_logic", "")
                rung_comm = r_ref.get("rung_comment", "")

                active_cls = "active" if f_idx == 0 else ""
                display_style = "block" if f_idx == 0 else "none"

                # Flow item for left sidebar
                sidebar_items_html.append(f"""
                <div class="flow-item {active_cls}" data-type="{item_type}" data-flow-idx="{f_idx}" onclick="selectFlowItem(this)">
                    <div class="flow-item-header">
                        <span class="flow-badge {badge_cls}">{badge_lbl}</span>
                        <span class="flow-rung-id">Rung {rung_num}</span>
                    </div>
                    <div class="flow-item-routine">{rout_name}</div>
                    <div class="flow-item-snippet">{html.escape(logic_text[:50])}...</div>
                </div>
                """)

                # Render components for right pane
                ladder_html = render_visual_rung_html(
                    logic_text,
                    rung_number=int(rung_num) if str(rung_num).isdigit() else f_idx,
                    comment=rung_comm or f"{tag_name} in {rout_name} Rung {rung_num}",
                    tag_descriptions=tag_descriptions,
                    unique_id=f"rung_dec_{idx}_f_{f_idx}",
                    target_tag=tag_name,
                )

                mermaid_flow = self.build_mermaid_flow({"NAME": tag_name, "LOGIC_SNIPPET": logic_text, "RATIONALE": dec.get("RATIONALE", "")}, tag_descriptions)
                mermaid_code = mermaid_flow.get("all", "")

                render_items_html.append(f"""
                <div class="flow-render-item {active_cls}" data-flow-idx="{f_idx}" style="display: {display_style};">
                    <div class="render-panel panel-ladder">
                        {ladder_html}
                    </div>
                    <div class="render-panel panel-mermaid" style="display: none;">
                        <div class="mermaid">
{mermaid_code}
                        </div>
                    </div>
                </div>
                """)

            sidebar_html = "".join(sidebar_items_html)
            render_html = "".join(render_items_html)

            cards_html.append(f"""
            <tr id="row-{idx}">
                <td class="center"><input type="checkbox" checked class="approve-check" data-idx="{idx}"></td>
                <td><strong class="tag-name">{tag_name}</strong><br><small class="text-muted">{dec.get("SCOPE", "")}</small></td>
                <td><div class="desc-display">{dec.get("PROPOSED_DESCRIPTION", "")}</div></td>
                <td><span class="badge {badge_class}">{conf}</span></td>
                <td><p class="rationale-text">{dec.get("RATIONALE", "")}</p></td>
                <td class="col-combined">
                    <div class="flow-component">
                        <!-- LEFT SIDEBAR: Common Signal Flow / Rung Selector -->
                        <div class="flow-sidebar">
                            <div class="flow-sidebar-header">
                                <span class="flow-sidebar-title">Signal Flows ({len(rung_refs)})</span>
                                <div class="flow-filter-pills">
                                    <button class="pill-btn active" onclick="filterSidebarRungs(this, 'all')">All</button>
                                    <button class="pill-btn pill-driver" onclick="filterSidebarRungs(this, 'driver')">🟢 Drivers ({driver_count})</button>
                                    <button class="pill-btn pill-driven" onclick="filterSidebarRungs(this, 'driven')">🟠 Driven ({driven_count})</button>
                                </div>
                            </div>
                            <div class="flow-list">
                                {sidebar_html}
                            </div>
                        </div>

                        <!-- RIGHT PANE: Render Area (Toggle Switch & Display) -->
                        <div class="flow-render-pane">
                            <div class="view-toggle-bar">
                                <button class="toggle-btn active" onclick="switchRenderView(this, 'ladder')">🪜 Ladder Diagram</button>
                                <button class="toggle-btn" onclick="switchRenderView(this, 'mermaid')">🔀 Signal Flow (Mermaid)</button>
                            </div>
                            <div class="render-view-wrapper">
                                {render_html}
                            </div>
                        </div>
                    </div>
                </td>
            </tr>
            """)

        table_rows = "".join(cards_html)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PLC Comment Audit Report - {project_name}</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <style>
        :root {{
            --bg-color: #0f172a;
            --panel-bg: #1e293b;
            --text-color: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: #334155;
            --primary: #38bdf8;
            --success: #4ade80;
            --warning: #facc15;
            --danger: #f87171;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 16px;
        }}
        .container {{
            width: 100%;
            max-width: 100%;
            margin: 0 auto;
        }}
        header {{
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 12px;
        }}
        h1 {{ margin: 0 0 8px 0; color: var(--primary); font-size: 24px; }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }}
        .metric-card {{
            background: var(--panel-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px;
            text-align: center;
        }}
        .metric-value {{ font-size: 26px; font-weight: bold; margin-top: 4px; }}
        .metric-value.high {{ color: var(--success); }}
        .metric-value.med {{ color: var(--warning); }}
        .metric-value.low {{ color: var(--danger); }}

        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--panel-bg);
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid var(--border-color);
            table-layout: auto;
        }}
        th, td {{
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
            vertical-align: top;
        }}
        th {{ background: #090d16; color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 11px; white-space: nowrap; }}
        .center {{ text-align: center; }}

        .tag-name {{ color: #e2e8f0; font-family: monospace; font-size: 13px; }}

        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
        }}
        .badge-high {{ background: rgba(74, 222, 128, 0.2); color: var(--success); border: 1px solid var(--success); }}
        .badge-med {{ background: rgba(250, 204, 21, 0.2); color: var(--warning); border: 1px solid var(--warning); }}
        .badge-low {{ background: rgba(248, 113, 113, 0.2); color: var(--danger); border: 1px solid var(--danger); }}

        .desc-display {{
            color: #38bdf8;
            font-weight: 600;
            font-size: 13px;
            line-height: 1.45;
            min-width: 170px;
            word-break: break-word;
        }}
        .rationale-text {{ margin: 0; font-size: 13px; line-height: 1.45; color: #cbd5e1; min-width: 180px; }}
        
        .col-combined {{
            width: 100%;
            min-width: 550px;
        }}
        .flow-component {{
            display: flex;
            gap: 12px;
            background: #090d16;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 10px;
        }}
        .flow-sidebar {{
            width: 220px;
            min-width: 220px;
            border-right: 1px solid var(--border-color);
            padding-right: 10px;
        }}
        .flow-sidebar-header {{
            margin-bottom: 8px;
        }}
        .flow-sidebar-title {{
            font-weight: 700;
            font-size: 11px;
            color: var(--primary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .flow-filter-pills {{
            display: flex;
            gap: 4px;
            margin-top: 6px;
        }}
        .pill-btn {{
            background: #1e293b;
            color: var(--text-muted);
            border: 1px solid var(--border-color);
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
            cursor: pointer;
            font-weight: 600;
        }}
        .pill-btn.active {{
            background: var(--primary);
            color: #0f172a;
            border-color: var(--primary);
        }}

        .flow-list {{
            display: flex;
            flex-direction: column;
            gap: 6px;
            max-height: 280px;
            overflow-y: auto;
        }}
        .flow-item {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 4px;
            padding: 6px 8px;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .flow-item:hover {{
            border-color: var(--primary);
        }}
        .flow-item.active {{
            border-color: var(--primary);
            background: #0f172a;
            box-shadow: 0 0 0 1px var(--primary);
        }}
        .flow-item-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2px;
        }}
        .flow-badge {{
            font-size: 9px;
            font-weight: 700;
            padding: 1px 4px;
            border-radius: 3px;
        }}
        .badge-driver {{ background: rgba(74, 222, 128, 0.2); color: var(--success); }}
        .badge-driven {{ background: rgba(251, 146, 60, 0.2); color: #fb923c; }}
        .flow-rung-id {{
            font-size: 10px;
            font-weight: bold;
            color: #f8fafc;
            font-family: monospace;
        }}
        .flow-item-routine {{
            font-size: 10px;
            color: var(--text-muted);
        }}
        .flow-item-snippet {{
            font-size: 9px;
            color: #a5f3fc;
            font-family: monospace;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-top: 2px;
        }}

        .flow-render-pane {{
            flex: 1;
            min-width: 0;
        }}
        .view-toggle-bar {{
            display: flex;
            gap: 6px;
            margin-bottom: 8px;
        }}
        .toggle-btn {{
            background: #1e293b;
            color: #94a3b8;
            border: 1px solid #334155;
            padding: 4px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 11px;
            font-weight: 600;
            transition: all 0.2s ease;
        }}
        .toggle-btn:hover {{
            background: #334155;
            color: #fff;
        }}
        .toggle-btn.active {{
            background: #38bdf8;
            color: #0f172a;
            border-color: #38bdf8;
        }}

        .text-muted {{ color: var(--text-muted); font-size: 12px; }}

        /* Mermaid Decision Node & Port Styles */
        .dec-node {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            text-align: center;
            padding: 4px 6px;
            box-sizing: border-box;
            white-space: normal;
            min-width: 160px;
        }}
        .dec-text {{
            flex: 1;
            font-size: 12px;
            line-height: 1.35;
            color: #f8fafc;
            font-weight: 600;
            text-align: center;
        }}
        .dec-ports {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            padding-left: 8px;
            border-left: 1px solid rgba(255, 255, 255, 0.25);
            margin-right: -2px;
        }}
        .dec-port {{
            font-size: 9px;
            font-weight: 800;
            padding: 3px 6px;
            border-radius: 3px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            text-align: center;
            line-height: 1;
        }}
        .dec-port.true {{
            background-color: #064e3b;
            color: #4ade80;
            border: 1px solid #059669;
        }}
        .dec-port.false {{
            background-color: #7f1d1d;
            color: #fca5a5;
            border: 1px solid #dc2626;
        }}
        .out-node {{
            font-size: 12px;
            line-height: 1.35;
            padding: 4px;
            text-align: center;
        }}
        
        {LADDER_RENDERER_CSS}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>PLC Tag Comment Review Dashboard</h1>
            <p class="text-muted">Project: {project_name} | Generated: {len(decisions)} Proposed Descriptions</p>
        </header>

        <div class="metrics-grid">
            <div class="metric-card">
                <div class="text-muted">Total Proposed</div>
                <div class="metric-value">{len(decisions)}</div>
            </div>
            <div class="metric-card">
                <div class="text-muted">High Confidence</div>
                <div class="metric-value high">{high_conf}</div>
            </div>
            <div class="metric-card">
                <div class="text-muted">Medium Confidence</div>
                <div class="metric-value med">{med_conf}</div>
            </div>
            <div class="metric-card">
                <div class="text-muted">Low Confidence</div>
                <div class="metric-value low">{low_conf}</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th class="center" style="width: 40px;">Approve</th>
                    <th style="width: 150px;">Tag / Scope</th>
                    <th style="width: 200px;">Proposed Description</th>
                    <th style="width: 90px;">Confidence</th>
                    <th style="width: 220px;">AI Reasoning</th>
                    <th style="width: 100%;">Visual Logic & Signal Flow</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
    <script>
    {LADDER_RENDERER_JS}
    if (typeof mermaid !== 'undefined') {{
        mermaid.initialize({{ startOnLoad: false, theme: 'dark', htmlLabels: true, securityLevel: 'loose' }});
    }}

    function getActiveViewMode(component) {{
        return component.getAttribute('data-view-mode') || 'ladder';
    }}

    function setActiveViewMode(component, mode) {{
        component.setAttribute('data-view-mode', mode);
    }}

    function styleMermaidLabels(container) {{
        container.querySelectorAll('.edgeLabel, .edgeLabel span, .edgeLabel tspan, .edgeLabel p, .edgeLabel div').forEach(function(el) {{
            var txt = (el.textContent || '').trim();
            if (txt === 'ON' || txt === 'PASS') {{
                el.style.backgroundColor = '#064e3b';
                el.style.color = '#4ade80';
                el.style.border = '1px solid #059669';
                el.style.borderRadius = '4px';
                el.style.padding = '1px 5px';
                el.style.fontWeight = 'bold';
                el.style.fontSize = '10px';
            }} else if (txt === 'OFF') {{
                el.style.backgroundColor = '#1e293b';
                el.style.color = '#94a3b8';
                el.style.border = '1px solid #475569';
                el.style.borderRadius = '4px';
                el.style.padding = '1px 5px';
                el.style.fontWeight = 'bold';
                el.style.fontSize = '10px';
            }}
        }});
    }}

    async function renderMermaidInPanel(panel) {{
        var mDiv = panel.querySelector('.mermaid');
        if (!mDiv) return;
        
        if (!mDiv.getAttribute('data-mermaid-code')) {{
            mDiv.setAttribute('data-mermaid-code', mDiv.textContent.trim());
        }}
        
        var code = mDiv.getAttribute('data-mermaid-code');
        if (!code) return;

        if (typeof mermaid !== 'undefined') {{
            try {{
                var uniqueId = 'svg_' + Math.random().toString(36).substring(2, 9);
                var renderRes = await mermaid.render(uniqueId, code);
                if (renderRes && renderRes.svg) {{
                    mDiv.innerHTML = renderRes.svg;
                    styleMermaidLabels(mDiv);
                }}
            }} catch (e) {{
                console.warn('Mermaid render caught:', e);
            }}
        }}
    }}

    function updateComponentPanels(component) {{
        var mode = getActiveViewMode(component);
        var activeItem = component.querySelector('.flow-render-item.active');
        if (!activeItem) activeItem = component.querySelector('.flow-render-item');
        if (!activeItem) return;

        var ladderPanel = activeItem.querySelector('.panel-ladder');
        var mermaidPanel = activeItem.querySelector('.panel-mermaid');

        if (mode === 'ladder') {{
            if (ladderPanel) ladderPanel.style.display = 'block';
            if (mermaidPanel) mermaidPanel.style.display = 'none';
        }} else {{
            if (ladderPanel) ladderPanel.style.display = 'none';
            if (mermaidPanel) {{
                mermaidPanel.style.display = 'block';
                renderMermaidInPanel(mermaidPanel);
            }}
        }}
    }}

    function selectFlowItem(item) {{
        var component = item.closest('.flow-component');
        component.querySelectorAll('.flow-item').forEach(function(i) {{ i.classList.remove('active'); }});
        item.classList.add('active');

        var flowIdx = item.getAttribute('data-flow-idx');
        component.querySelectorAll('.flow-render-item').forEach(function(r) {{
            if (r.getAttribute('data-flow-idx') === flowIdx) {{
                r.classList.add('active');
                r.style.display = 'block';
            }} else {{
                r.classList.remove('active');
                r.style.display = 'none';
            }}
        }});

        updateComponentPanels(component);
    }}

    function filterSidebarRungs(btn, type) {{
        var sidebar = btn.closest('.flow-sidebar');
        sidebar.querySelectorAll('.pill-btn').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');

        sidebar.querySelectorAll('.flow-item').forEach(function(item) {{
            var itemType = item.getAttribute('data-type');
            if (type === 'all' || itemType === type) {{
                item.style.display = 'block';
            }} else {{
                item.style.display = 'none';
            }}
        }});
    }}

    function switchRenderView(btn, viewType) {{
        var component = btn.closest('.flow-component');
        var renderPane = btn.closest('.flow-render-pane');
        renderPane.querySelectorAll('.toggle-btn').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');

        setActiveViewMode(component, viewType);
        updateComponentPanels(component);
    }}

    document.addEventListener('DOMContentLoaded', function() {{
        document.querySelectorAll('.flow-component').forEach(function(comp) {{
            updateComponentPanels(comp);
        }});
    }});
    </script>
</body>
</html>"""

    def manage_incremental_memory(
        self,
        file_path: str | Path,
        memory_file_path: str | Path,
        decisions_to_save: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Granular object-level memory tracker. Calculates SHA-256 hashes per Routine and Tag Table,
        diffing against memory to skip unchanged logic while updating modified routines.
        """
        l5x_path = self.resolve_l5x_path(file_path)
        root = self.parse_l5x_tree(l5x_path)
        mem_path = Path(memory_file_path).resolve()

        # Load existing memory if available
        memory_data = {"project": l5x_path.stem, "routines": {}, "tags": {}}
        if mem_path.exists():
            try:
                memory_data = json.loads(mem_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Could not load memory file {mem_path}: {e}")

        # Compute current routine hashes
        current_routine_hashes: Dict[str, str] = {}
        for program in root.findall(".//Programs/Program"):
            prog_name = program.attrib.get("Name", "MainProgram")
            for routine in program.findall(".//Routine"):
                rout_name = routine.attrib.get("Name", "")
                key = f"{prog_name}/{rout_name}"
                # Serialize routine text & rungs to bytes for hashing
                rout_str = ET.tostring(routine, encoding="utf-8")
                current_routine_hashes[key] = hashlib.sha256(rout_str).hexdigest()

        # Diff against saved hashes
        saved_routine_hashes = memory_data.get("routines", {})
        unchanged_routines = []
        modified_routines = []

        for key, curr_hash in current_routine_hashes.items():
            if saved_routine_hashes.get(key) == curr_hash:
                unchanged_routines.append(key)
            else:
                modified_routines.append(key)

        # Merge decisions into tag memory if provided
        if decisions_to_save:
            tags_mem = memory_data.setdefault("tags", {})
            for dec in decisions_to_save:
                name = dec.get("NAME")
                if name:
                    tags_mem[name] = {
                        "proposed_description": dec.get("PROPOSED_DESCRIPTION"),
                        "rationale": dec.get("RATIONALE"),
                        "confidence": dec.get("CONFIDENCE"),
                        "logic_snippet": dec.get("LOGIC_SNIPPET"),
                        "status": "PROPOSED",
                    }

        # Update saved routine hashes
        memory_data["routines"] = current_routine_hashes

        # Save memory
        mem_path.parent.mkdir(parents=True, exist_ok=True)
        mem_path.write_text(json.dumps(memory_data, indent=2), encoding="utf-8")

        return {
            "memory_file": str(mem_path),
            "total_routines": len(current_routine_hashes),
            "unchanged_routines_count": len(unchanged_routines),
            "modified_routines_count": len(modified_routines),
            "unchanged_routines": unchanged_routines,
            "modified_routines": modified_routines,
            "saved_tags_count": len(memory_data.get("tags", {})),
        }
