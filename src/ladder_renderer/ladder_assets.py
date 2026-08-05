"""
Ladder Renderer Embedded Assets & HTML Helpers
"""

import json
from typing import Any, Dict, Optional
from .ladder_to_dot import convert_rung_to_model

LADDER_RENDERER_CSS = """
/* Embedded Portable Ladder Renderer CSS */
.ladder-rung-card {
    background: #090d16;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 12px;
    margin-top: 8px;
}
.ladder-rung-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid #1e293b;
}
.ladder-rung-title {
    font-size: 13px;
    font-weight: 700;
    color: #38bdf8;
    font-family: monospace;
}
.ladder-rung-comment {
    color: #4ade80;
    font-size: 12px;
    font-style: italic;
    margin-bottom: 8px;
    line-height: 1.4;
}
.ladder-svg-container {
    background: #ffffff;
    border-radius: 4px;
    padding: 8px;
    overflow-x: auto;
    margin-bottom: 8px;
}
.ladder-svg-container svg {
    display: block;
    width: 100%;
    height: auto;
}
.ladder-text-raw {
    background: #0f172a;
    color: #a5f3fc;
    padding: 6px 10px;
    border-radius: 4px;
    font-family: 'Consolas', 'Cascadia Mono', monospace;
    font-size: 11px;
    white-space: pre-wrap;
    word-break: break-all;
    border: 1px solid #1e293b;
}
.tag-clickable {
    cursor: pointer;
}
.target-highlighted-node text {
    fill: #0284c7 !important;
    font-weight: bold !important;
}
.target-highlighted-node rect,
.target-highlighted-node circle,
.target-highlighted-node path,
.target-highlighted-node line {
    stroke: #0284c7 !important;
    stroke-width: 2.5px !important;
    filter: drop-shadow(0px 0px 4px rgba(2, 132, 199, 0.6));
}
"""

_JS_BODY = "        // ===== Custom SVG ladder renderer =====================================\n        // Lays out each rung directly (no auto-layout engine): left rail at x=0,\n        // right rail at x=W, input instructions left, output coils right-justified\n        // hard against the right rail with a long flow wire between. Deterministic\n        // and responsive - re-rendering at a new width just repositions the rails.\n        const LAD = {\n            INK: '#14171B', OP: '#0B4F9E', LABEL: '#5B636E', GREEN: '#0B7A45',\n            HEADBG: '#EEF1F4', WIRE: '#5A636E', RAIL: '#3A4149',\n            LINEH: 16, ROWH: 18, HEADH: 20, GLYPHH: 20,\n            PADX: 8, HGAP: 30, VGAP: 16, GUT: 12, TOP: 10, BOT: 10,\n            RAILW: 2, MINGAP: 28\n        };\n        const LAD_ZOOM = 1.45;          // default on-screen magnification of ladders\n        const LAD_NS = 'http://www.w3.org/2000/svg';\n        const LAD_MONO = 'Consolas, \"Cascadia Mono\", \"Courier New\", monospace';\n        const _ladMeasure = document.createElement('canvas').getContext('2d');\n        function ladTextW(s, size, bold) {\n            _ladMeasure.font = (bold ? 'bold ' : '') + (size || 12) + 'px ' + LAD_MONO;\n            return _ladMeasure.measureText(s || '').width;\n        }\n        function svgEl(tag, attrs) {\n            const e = document.createElementNS(LAD_NS, tag);\n            if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);\n            return e;\n        }\n        function ladLine(g, x1, y1, x2, y2, w) {\n            g.appendChild(svgEl('line', { x1: x1, y1: y1, x2: x2, y2: y2,\n                stroke: LAD.WIRE, 'stroke-width': w || 1.4, 'stroke-linecap': 'round' }));\n        }\n        function ladCellColor(cls) {\n            return cls === 'tag' ? LAD.OP : (cls === 'label' ? LAD.LABEL : LAD.INK);\n        }\n        function ladText(g, x, y, s, color, anchor, size, o) {\n            o = o || {};\n            const t = svgEl('text', { x: x, y: y, fill: color, 'font-family': LAD_MONO,\n                'font-size': size || 12, 'text-anchor': anchor || 'start',\n                'dominant-baseline': 'middle' });\n            if (o.bold) t.setAttribute('font-weight', '700');\n            if (o.italic) t.setAttribute('font-style', 'italic');\n            t.textContent = s;\n            if (o.tag) ladMakeClickable(t, s);\n            g.appendChild(t);\n            return t;\n        }\n        // Tag description (green): left-anchored at the element, but clamped so a\n        // long description never runs off either edge of the canvas.\n        let _ladCurW = 0;\n        function ladDescText(g, leftX, y, s) {\n            const w = ladTextW(s, 10);\n            let x = leftX;\n            if (x + w > _ladCurW - 4) x = Math.max(4, _ladCurW - 4 - w);\n            ladText(g, x, y, s, LAD.GREEN, 'start', 10, { italic: true });\n        }\n        function ladMakeClickable(t, ref) {\n            const base = (ref || '').split('.')[0].split('[')[0];\n            if (!base || !tagData.some(td => td.name === base)) return;\n            t.classList.add('tag-clickable');\n            t.setAttribute('data-base', base);\n            t.style.cursor = 'pointer';\n            t.addEventListener('click', e => { e.stopPropagation(); showUsages(ref); });\n            const title = svgEl('title'); title.textContent = 'Cross-reference ' + ref; t.appendChild(title);\n        }\n\n        // Wrap one component's primitives in a <g class=\"lad-comp\"> tagged with the\n        // base tag names it references, so the Colorize feature can target it.\n        function ladDrawComp(g, drawInto) {\n            const cg = svgEl('g', { 'class': 'lad-comp' });\n            drawInto(cg);\n            const bases = [];\n            cg.querySelectorAll('text[data-base]').forEach(function (t) {\n                const b = t.getAttribute('data-base');\n                if (b && bases.indexOf(b) < 0) bases.push(b);\n            });\n            if (bases.length) cg.setAttribute('data-tags', bases.join('|'));\n            g.appendChild(cg);\n        }\n\n        // --- Measurement: each node returns { w, up, down, draw(g, x, wireY) } ---\n        function ladMeasureItem(item) {\n            if (item.e) return ladMeasureEl(item.e);\n            if (item.p) return ladMeasureGroup(item.p);\n            return { w: 0, up: 0, down: 0, draw: function () {} };\n        }\n        function ladMeasureEl(el) {\n            if (el.r === 'contact' || el.r === 'coil') {\n                const w = Math.max(28, ladTextW(el.tag, 12), el.desc ? ladTextW(el.desc, 10) : 0) + 8;\n                let up = LAD.GLYPHH / 2;\n                if (el.tag) up += LAD.LINEH;\n                if (el.desc) up += LAD.LINEH;\n                return { w: w, up: up, down: LAD.GLYPHH / 2,\n                    draw: function (g, x, wireY) { ladDrawComp(g, function (cg) { ladDrawSymbol(cg, x, wireY, w, el); }); } };\n            }\n            return ladMeasureBlock(el);\n        }\n        function ladMeasureBlock(el) {\n            const headW = ladTextW(el.head, 12, true);\n            const subW = el.sub ? ladTextW(el.sub, 9) : 0;\n            let labelColW = 0, valColW = 0, singleW = 0;\n            (el.rows || []).forEach(function (row) {\n                if (row.length === 2) {\n                    labelColW = Math.max(labelColW, ladTextW(row[0][0], 11));\n                    valColW = Math.max(valColW, ladTextW(row[1][0], 12));\n                } else {\n                    singleW = Math.max(singleW, ladTextW(row[0][0], 12));\n                }\n            });\n            const rowsW = Math.max(singleW, labelColW + valColW + (labelColW && valColW ? 12 : 0));\n            const w = Math.max(headW, subW, rowsW) + LAD.PADX * 2;\n            const headH = LAD.HEADH + (el.sub ? 11 : 0);\n            const blockH = headH + (el.rows || []).length * LAD.ROWH;\n            let up = blockH / 2;\n            if (el.desc) up += LAD.LINEH;\n            return { w: w, up: up, down: blockH / 2,\n                draw: function (g, x, wireY) { ladDrawComp(g, function (cg) { ladDrawBlock(cg, x, wireY, w, blockH, headH, labelColW, el); }); } };\n        }\n        function ladMeasureSeries(items) {\n            const boxes = (items || []).map(ladMeasureItem);\n            let w = 0, up = 0, down = 0;\n            boxes.forEach(function (b, i) {\n                w += b.w; if (i) w += LAD.HGAP;\n                up = Math.max(up, b.up); down = Math.max(down, b.down);\n            });\n            return { w: w, up: up, down: down,\n                draw: function (g, x, wireY) {\n                    let cx = x;\n                    boxes.forEach(function (b, i) {\n                        if (i) ladLine(g, cx - LAD.HGAP, wireY, cx, wireY);\n                        b.draw(g, cx, wireY);\n                        cx += b.w + LAD.HGAP;\n                    });\n                } };\n        }\n        function ladMeasureGroup(branches) {\n            const subs = branches.map(function (b) { return ladMeasureSeries(b.s); });\n            const w = Math.max.apply(null, subs.map(function (s) { return s.w; }).concat([0]));\n            const yps = []; let bottom;\n            yps[0] = 0; bottom = subs[0].down;\n            for (let i = 1; i < subs.length; i++) {\n                yps[i] = bottom + LAD.VGAP + subs[i].up;\n                bottom = yps[i] + subs[i].down;\n            }\n            return { w: w, up: subs[0].up, down: bottom,\n                draw: function (g, x, wireY) {\n                    const y0 = wireY + yps[0], yN = wireY + yps[yps.length - 1];\n                    if (subs.length > 1) { ladLine(g, x, y0, x, yN); ladLine(g, x + w, y0, x + w, yN); }\n                    subs.forEach(function (s, i) {\n                        const wy = wireY + yps[i];\n                        s.draw(g, x, wy);\n                        if (s.w < w) ladLine(g, x + s.w, wy, x + w, wy);\n                    });\n                } };\n        }\n\n        // --- Drawing primitives for a single element ---\n        function ladDrawSymbol(g, x, wireY, w, el) {\n            const cx = x + w / 2;\n            // Conductor stops at the symbol terminals - it must not run *through*\n            // the contact gap or the coil. Left stub, gap for the symbol, right stub.\n            const gap = (el.r === 'contact') ? 5 : 10;\n            ladLine(g, x, wireY, cx - gap, wireY);\n            ladLine(g, cx + gap, wireY, x + w, wireY);\n            let ty = wireY - LAD.GLYPHH / 2 - 5;\n            if (el.tag) { ladText(g, cx, ty, el.tag, LAD.OP, 'middle', 12, { tag: true }); ty -= LAD.LINEH; }\n            if (el.desc) ladDescText(g, x, ty, el.desc);\n            const half = LAD.GLYPHH / 2 - 1;\n            if (el.r === 'contact') {\n                ladSeg(g, cx - 5, wireY - half, cx - 5, wireY + half);\n                ladSeg(g, cx + 5, wireY - half, cx + 5, wireY + half);\n                if (el.g === 'nc') ladSeg(g, cx - 8, wireY + half, cx + 8, wireY - half, 1.3);\n            } else {\n                g.appendChild(svgEl('path', { d: 'M ' + (cx - 4) + ' ' + (wireY - half) + ' Q ' + (cx - 12) + ' ' + wireY + ' ' + (cx - 4) + ' ' + (wireY + half), fill: 'none', stroke: LAD.INK, 'stroke-width': 1.6 }));\n                g.appendChild(svgEl('path', { d: 'M ' + (cx + 4) + ' ' + (wireY - half) + ' Q ' + (cx + 12) + ' ' + wireY + ' ' + (cx + 4) + ' ' + (wireY + half), fill: 'none', stroke: LAD.INK, 'stroke-width': 1.6 }));\n                if (el.g === 'otl') ladText(g, cx, wireY, 'L', LAD.INK, 'middle', 10, { bold: true });\n                if (el.g === 'otu') ladText(g, cx, wireY, 'U', LAD.INK, 'middle', 10, { bold: true });\n            }\n            const title = svgEl('title'); title.textContent = el.tip || ''; g.appendChild(title);\n        }\n        function ladSeg(g, x1, y1, x2, y2, w) {\n            g.appendChild(svgEl('line', { x1: x1, y1: y1, x2: x2, y2: y2,\n                stroke: LAD.INK, 'stroke-width': w || 1.6, 'stroke-linecap': 'round' }));\n        }\n        function ladDrawBlock(g, x, wireY, w, blockH, headH, labelColW, el) {\n            const top = wireY - blockH / 2;\n            ladLine(g, x - 1, wireY, x, wireY);                 // entry stub\n            ladLine(g, x + w, wireY, x + w + 1, wireY);         // exit stub\n            if (el.desc) ladDescText(g, x, top - 8, el.desc);\n            g.appendChild(svgEl('rect', { x: x, y: top, width: w, height: blockH, fill: '#ffffff', stroke: LAD.INK, 'stroke-width': 1.2, rx: 1 }));\n            g.appendChild(svgEl('rect', { x: x, y: top, width: w, height: headH, fill: LAD.HEADBG, stroke: LAD.INK, 'stroke-width': 1.2 }));\n            ladText(g, x + w / 2, top + (el.sub ? 10 : headH / 2), el.head, LAD.INK, 'middle', 12, { bold: true });\n            if (el.sub) ladText(g, x + w / 2, top + headH - 6, el.sub, LAD.LABEL, 'middle', 9, { italic: true });\n            let ry = top + headH;\n            (el.rows || []).forEach(function (row) {\n                const cy = ry + LAD.ROWH / 2;\n                if (row.length === 2) {\n                    ladText(g, x + LAD.PADX + labelColW, cy, row[0][0], LAD.LABEL, 'end', 11);\n                    ladText(g, x + LAD.PADX + labelColW + 12, cy, row[1][0], ladCellColor(row[1][1]), 'start', 12, { tag: row[1][1] === 'tag' });\n                } else {\n                    ladText(g, x + LAD.PADX, cy, row[0][0], ladCellColor(row[0][1]), 'start', 12, { tag: row[0][1] === 'tag' });\n                }\n                ry += LAD.ROWH;\n            });\n            const title = svgEl('title'); title.textContent = el.tip || ''; g.appendChild(title);\n        }\n\n        // --- Top-level: build the <svg> for a rung model into `container` ---\n        function renderLadder(container, model) {\n            container.innerHTML = '';\n            container.style.overflowX = 'auto';\n            const inner = ladMeasureSeries(model.s ? model.s.s : []);\n            const outs = (model.out || []).map(ladMeasureEl);\n            let oyps = [], oUp = 0, oDown = 0, maxOutW = 0;\n            if (outs.length) {\n                oyps[0] = 0; let bottom = outs[0].down; oUp = outs[0].up;\n                for (let i = 1; i < outs.length; i++) {\n                    oyps[i] = bottom + LAD.VGAP + outs[i].up; bottom = oyps[i] + outs[i].down;\n                }\n                oDown = bottom;\n                maxOutW = Math.max.apply(null, outs.map(function (o) { return o.w; }));\n            }\n            const up = Math.max(inner.up, oUp, LAD.GLYPHH / 2);\n            const down = Math.max(inner.down, oDown, LAD.GLYPHH / 2);\n            const wireY = LAD.TOP + up;\n            const H = Math.ceil(LAD.TOP + up + down + LAD.BOT);\n\n            const leftX = LAD.RAILW;\n            const inStartX = leftX + LAD.GUT;\n            const inRight = inStartX + inner.w;\n            let needW = inRight + LAD.GUT;\n            if (outs.length) needW = inRight + LAD.MINGAP + maxOutW + LAD.GUT * 2;\n\n            // Layout happens in logical units; the whole SVG is then displayed\n            // scaled up by LAD_ZOOM so the text reads comfortably. Available width\n            // is divided by the zoom so the rail still lands on the container edge.\n            const cs = getComputedStyle(container);\n            const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);\n            const availW = Math.max(((container.clientWidth || 1) - pad) / LAD_ZOOM, 120);\n            const W = Math.ceil(Math.max(availW, needW));\n            const rightX = W - LAD.RAILW;\n            _ladCurW = W;\n\n            const svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H,\n                width: Math.round(W * LAD_ZOOM), height: Math.round(H * LAD_ZOOM) });\n            svg.style.maxWidth = 'none'; svg.style.display = 'block';\n            const g = svgEl('g'); svg.appendChild(g);\n            // Power rails\n            g.appendChild(svgEl('line', { x1: leftX, y1: 0, x2: leftX, y2: H, stroke: LAD.RAIL, 'stroke-width': LAD.RAILW + 1 }));\n            g.appendChild(svgEl('line', { x1: rightX, y1: 0, x2: rightX, y2: H, stroke: LAD.RAIL, 'stroke-width': LAD.RAILW + 1 }));\n            ladLine(g, leftX, wireY, inStartX, wireY);\n            inner.draw(g, inStartX, wireY);\n            if (outs.length) {\n                const outRight = rightX - LAD.GUT;\n                const joinX = outRight - maxOutW;\n                ladLine(g, inRight, wireY, joinX, wireY);        // long flow wire\n                if (outs.length > 1) ladLine(g, joinX, wireY + oyps[0], joinX, wireY + oyps[oyps.length - 1]);\n                outs.forEach(function (o, i) {\n                    const wy = wireY + oyps[i];\n                    const ox = outRight - o.w;                    // right-justified\n                    if (ox > joinX) ladLine(g, joinX, wy, ox, wy);\n                    o.draw(g, ox, wy);\n                    ladLine(g, ox + o.w, wy, rightX, wy);\n                });\n            } else {\n                ladLine(g, inRight, wireY, rightX, wireY);\n            }\n            container.appendChild(svg);\n            return svg;\n        }\n\n        function renderSingleLadder(container) {\n            const key = container.dataset.rungKey;\n            if (!key || container.dataset.rendered === 'true') return;\n            const model = rungData[key];\n            if (!model) {\n                container.innerHTML = '<span style=\"color:#999;font-style:italic;\">Diagram unavailable</span>';\n                container.dataset.rendered = 'true';\n                return;\n            }\n            try {\n                renderLadder(container, model);\n                container._ladModel = model;\n                container._ladW = Math.round(container.clientWidth);\n                container.dataset.rendered = 'true';\n                ladderResizeObserver.observe(container);\n                if (colorizeOn) colorizeContainer(container);\n                if (typeof scheduleMinimapRebuild === 'function') scheduleMinimapRebuild();\n            } catch (e) {\n                container.innerHTML = '<span style=\"color:#999;font-style:italic;\">Diagram error: ' + e.message + '</span>';\n                container.dataset.rendered = 'true';\n            }\n        }\n\n        // Re-render a rung when its container's width actually changes (sidebar\n        // toggle, window resize). Width is the only trigger; ignore height-only\n        // changes (our own render alters svg height and would otherwise loop).\n        const ladderResizeObserver = new ResizeObserver(function (entries) {\n            entries.forEach(function (entry) {\n                const c = entry.target;\n                if (c.dataset.rendered !== 'true' || !c._ladModel) return;\n                const w = Math.round(entry.contentRect.width);\n                if (!w || c._ladW === w) return;\n                c._ladW = w;\n                try { renderLadder(c, c._ladModel); if (colorizeOn) colorizeContainer(c); } catch (e) {}\n                if (typeof scheduleMinimapRebuild === 'function') scheduleMinimapRebuild();\n            });\n        });\n\n"

LADDER_RENDERER_JS = """
if (typeof tagData === 'undefined') var tagData = [];
if (typeof showUsages === 'undefined') var showUsages = function(t) { console.log('Tag reference:', t); };
if (typeof colorizeOn === 'undefined') var colorizeOn = false;
if (typeof colorizeContainer === 'undefined') var colorizeContainer = function() {};

""" + _JS_BODY + """

window.highlightTargetTagInSvg = function(container) {
    var targetTag = container.getAttribute('data-target-tag');
    if (!targetTag) return;
    var targetBase = targetTag.split('.')[0].split('[')[0];
    
    var svg = container.querySelector('svg');
    if (!svg) return;
    
    svg.querySelectorAll('text').forEach(function(t) {
        var txt = (t.textContent || '').strip ? t.textContent.trim() : '';
        if (txt && (txt === targetTag || txt.indexOf(targetTag) >= 0 || txt.indexOf(targetBase) >= 0)) {
            t.setAttribute('fill', '#0284c7');
            t.setAttribute('font-weight', '700');
            var parentG = t.closest('g') || t.parentNode;
            if (parentG) {
                parentG.classList.add('target-highlighted-node');
            }
        }
    });
};

window.renderAllLadderRungs = function() {
    document.querySelectorAll('.ladder-svg-container[data-rung-key]').forEach(function(c) {
        if (typeof renderSingleLadder === 'function') {
            renderSingleLadder(c);
            window.highlightTargetTagInSvg(c);
        }
    });
};
if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(window.renderAllLadderRungs, 50);
} else {
    document.addEventListener('DOMContentLoaded', window.renderAllLadderRungs);
}
"""


def render_visual_rung_html(
    rung_text: str,
    rung_number: int = 0,
    comment: str = "",
    tag_descriptions: Optional[Dict[str, str]] = None,
    unique_id: str = "rung_0",
    target_tag: str = "",
) -> str:
    """Convert ladder logic text to visual HTML/SVG diagram component."""
    if not rung_text:
        return '<span class="text-muted">No snippet available</span>'

    try:
        model = convert_rung_to_model(rung_text, rung_number=rung_number, comment=comment, tag_descriptions=tag_descriptions)
        model_json = json.dumps(model)
        
        script_snippet = f'<script>if (!window.rungData) window.rungData = {{}}; window.rungData["{unique_id}"] = {model_json};</script>'
        
        comment_html = f'<div class="ladder-rung-comment">{comment}</div>' if comment else ''
        
        card_html = f"""
        <div class="ladder-rung-card">
            <div class="ladder-rung-header">
                <span class="ladder-rung-title">RUNG {rung_number}</span>
            </div>
            {comment_html}
            {script_snippet}
            <div class="ladder-svg-container" data-rung-key="{unique_id}" data-target-tag="{target_tag}"></div>
            <div class="ladder-text-raw">{rung_text}</div>
        </div>
        """
        return card_html
    except Exception as e:
        return f'<div class="code-block">{rung_text}</div>'
