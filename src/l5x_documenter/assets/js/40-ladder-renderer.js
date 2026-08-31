        // ===== Custom SVG ladder renderer =====================================
        // Lays out each rung directly (no auto-layout engine): left rail at x=0,
        // right rail at x=W, input instructions left, output coils right-justified
        // hard against the right rail with a long flow wire between. Deterministic
        // and responsive - re-rendering at a new width just repositions the rails.
        const LAD = {
            INK: '#14171B', OP: '#0B4F9E', LABEL: '#5B636E', GREEN: '#0B7A45',
            HEADBG: '#EEF1F4', WIRE: '#5A636E', RAIL: '#3A4149',
            LINEH: 16, ROWH: 18, HEADH: 20, GLYPHH: 20,
            PADX: 8, HGAP: 30, VGAP: 16, GUT: 12, TOP: 10, BOT: 10,
            RAILW: 2, MINGAP: 28
        };
        const LAD_ZOOM = 1.45;          // default on-screen magnification of ladders
        const LAD_NS = 'http://www.w3.org/2000/svg';
        const LAD_MONO = 'Consolas, "Cascadia Mono", "Courier New", monospace';
        const _ladMeasure = document.createElement('canvas').getContext('2d');
        function ladTextW(s, size, bold) {
            _ladMeasure.font = (bold ? 'bold ' : '') + (size || 12) + 'px ' + LAD_MONO;
            return _ladMeasure.measureText(s || '').width;
        }
        function svgEl(tag, attrs) {
            const e = document.createElementNS(LAD_NS, tag);
            if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
            return e;
        }
        function ladLine(g, x1, y1, x2, y2, w) {
            g.appendChild(svgEl('line', { x1: x1, y1: y1, x2: x2, y2: y2,
                stroke: LAD.WIRE, 'stroke-width': w || 1.4, 'stroke-linecap': 'round' }));
        }
        function ladCellColor(cls) {
            return cls === 'tag' ? LAD.OP : (cls === 'label' ? LAD.LABEL : LAD.INK);
        }
        function ladText(g, x, y, s, color, anchor, size, o) {
            o = o || {};
            const t = svgEl('text', { x: x, y: y, fill: color, 'font-family': LAD_MONO,
                'font-size': size || 12, 'text-anchor': anchor || 'start',
                'dominant-baseline': 'middle' });
            if (o.bold) t.setAttribute('font-weight', '700');
            if (o.italic) t.setAttribute('font-style', 'italic');
            t.textContent = s;
            if (o.tag) ladMakeClickable(t, s);
            g.appendChild(t);
            return t;
        }
        // Tag description (green): left-anchored at the element, but clamped so a
        // long description never runs off either edge of the canvas.
        let _ladCurW = 0;
        function ladDescText(g, leftX, y, s) {
            const w = ladTextW(s, 10);
            let x = leftX;
            if (x + w > _ladCurW - 4) x = Math.max(4, _ladCurW - 4 - w);
            ladText(g, x, y, s, LAD.GREEN, 'start', 10, { italic: true });
        }
        function ladMakeClickable(t, ref) {
            const base = (ref || '').split('.')[0].split('[')[0];
            if (!base || !tagData.some(td => td.name === base)) return;
            t.classList.add('tag-clickable');
            t.setAttribute('data-base', base);
            t.style.cursor = 'pointer';
            t.addEventListener('click', e => { e.stopPropagation(); showUsages(ref); });
            const title = svgEl('title'); title.textContent = 'Cross-reference ' + ref; t.appendChild(title);
        }

        // Wrap one component's primitives in a <g class="lad-comp"> tagged with the
        // base tag names it references, so the Colorize feature can target it.
        function ladDrawComp(g, drawInto) {
            const cg = svgEl('g', { 'class': 'lad-comp' });
            drawInto(cg);
            const bases = [];
            cg.querySelectorAll('text[data-base]').forEach(function (t) {
                const b = t.getAttribute('data-base');
                if (b && bases.indexOf(b) < 0) bases.push(b);
            });
            if (bases.length) cg.setAttribute('data-tags', bases.join('|'));
            g.appendChild(cg);
        }

        // --- Measurement: each node returns { w, up, down, draw(g, x, wireY) } ---
        function ladMeasureItem(item) {
            if (item.e) return ladMeasureEl(item.e);
            if (item.p) return ladMeasureGroup(item.p);
            return { w: 0, up: 0, down: 0, draw: function () {} };
        }
        function ladMeasureEl(el) {
            if (el.r === 'contact' || el.r === 'coil') {
/*I18N-BI-START*/
                const desc = pickLang(el.desc);
                const w = Math.max(28, ladTextW(el.tag, 12), desc ? ladTextW(desc, 10) : 0) + 8;
                let up = LAD.GLYPHH / 2;
                if (el.tag) up += LAD.LINEH;
                if (desc) up += LAD.LINEH;
/*I18N-BI-END*/
/*I18N-BASE-START*/
                const w = Math.max(28, ladTextW(el.tag, 12), el.desc ? ladTextW(el.desc, 10) : 0) + 8;
                let up = LAD.GLYPHH / 2;
                if (el.tag) up += LAD.LINEH;
                if (el.desc) up += LAD.LINEH;
/*I18N-BASE-END*/
                return { w: w, up: up, down: LAD.GLYPHH / 2,
                    draw: function (g, x, wireY) { ladDrawComp(g, function (cg) { ladDrawSymbol(cg, x, wireY, w, el); }); } };
            }
            return ladMeasureBlock(el);
        }
        function ladMeasureBlock(el) {
/*I18N-BI-START*/
            const headW = ladTextW(pickLang(el.head), 12, true);
/*I18N-BI-END*/
/*I18N-BASE-START*/
            const headW = ladTextW(el.head, 12, true);
/*I18N-BASE-END*/
            const subW = el.sub ? ladTextW(el.sub, 9) : 0;
            let labelColW = 0, valColW = 0, singleW = 0;
            (el.rows || []).forEach(function (row) {
                if (row.length === 2) {
                    labelColW = Math.max(labelColW, ladTextW(row[0][0], 11));
                    valColW = Math.max(valColW, ladTextW(row[1][0], 12));
                } else {
                    singleW = Math.max(singleW, ladTextW(row[0][0], 12));
                }
            });
            const rowsW = Math.max(singleW, labelColW + valColW + (labelColW && valColW ? 12 : 0));
            const w = Math.max(headW, subW, rowsW) + LAD.PADX * 2;
            const headH = LAD.HEADH + (el.sub ? 11 : 0);
            const blockH = headH + (el.rows || []).length * LAD.ROWH;
            let up = blockH / 2;
/*I18N-BI-START*/
            if (pickLang(el.desc)) up += LAD.LINEH;
/*I18N-BI-END*/
/*I18N-BASE-START*/
            if (el.desc) up += LAD.LINEH;
/*I18N-BASE-END*/
            return { w: w, up: up, down: blockH / 2,
                draw: function (g, x, wireY) { ladDrawComp(g, function (cg) { ladDrawBlock(cg, x, wireY, w, blockH, headH, labelColW, el); }); } };
        }
        function ladMeasureSeries(items) {
            const boxes = (items || []).map(ladMeasureItem);
            let w = 0, up = 0, down = 0;
            boxes.forEach(function (b, i) {
                w += b.w; if (i) w += LAD.HGAP;
                up = Math.max(up, b.up); down = Math.max(down, b.down);
            });
            return { w: w, up: up, down: down,
                draw: function (g, x, wireY) {
                    let cx = x;
                    boxes.forEach(function (b, i) {
                        if (i) ladLine(g, cx - LAD.HGAP, wireY, cx, wireY);
                        b.draw(g, cx, wireY);
                        cx += b.w + LAD.HGAP;
                    });
                } };
        }
        function ladMeasureGroup(branches) {
            const subs = branches.map(function (b) { return ladMeasureSeries(b.s); });
            const w = Math.max.apply(null, subs.map(function (s) { return s.w; }).concat([0]));
            const yps = []; let bottom;
            yps[0] = 0; bottom = subs[0].down;
            for (let i = 1; i < subs.length; i++) {
                yps[i] = bottom + LAD.VGAP + subs[i].up;
                bottom = yps[i] + subs[i].down;
            }
            return { w: w, up: subs[0].up, down: bottom,
                draw: function (g, x, wireY) {
                    const y0 = wireY + yps[0], yN = wireY + yps[yps.length - 1];
                    if (subs.length > 1) { ladLine(g, x, y0, x, yN); ladLine(g, x + w, y0, x + w, yN); }
                    subs.forEach(function (s, i) {
                        const wy = wireY + yps[i];
                        s.draw(g, x, wy);
                        if (s.w < w) ladLine(g, x + s.w, wy, x + w, wy);
                    });
                } };
        }

        // --- Drawing primitives for a single element ---
        function ladDrawSymbol(g, x, wireY, w, el) {
            const cx = x + w / 2;
            // Conductor stops at the symbol terminals - it must not run *through*
            // the contact gap or the coil. Left stub, gap for the symbol, right stub.
            const gap = (el.r === 'contact') ? 5 : 10;
            ladLine(g, x, wireY, cx - gap, wireY);
            ladLine(g, cx + gap, wireY, x + w, wireY);
            let ty = wireY - LAD.GLYPHH / 2 - 5;
            if (el.tag) { ladText(g, cx, ty, el.tag, LAD.OP, 'middle', 12, { tag: true }); ty -= LAD.LINEH; }
/*I18N-BI-START*/
            const desc = pickLang(el.desc);
            if (desc) ladDescText(g, x, ty, desc);
/*I18N-BI-END*/
/*I18N-BASE-START*/
            if (el.desc) ladDescText(g, x, ty, el.desc);
/*I18N-BASE-END*/
            const half = LAD.GLYPHH / 2 - 1;
            if (el.r === 'contact') {
                ladSeg(g, cx - 5, wireY - half, cx - 5, wireY + half);
                ladSeg(g, cx + 5, wireY - half, cx + 5, wireY + half);
                if (el.g === 'nc') ladSeg(g, cx - 8, wireY + half, cx + 8, wireY - half, 1.3);
            } else {
                g.appendChild(svgEl('path', { d: 'M ' + (cx - 4) + ' ' + (wireY - half) + ' Q ' + (cx - 12) + ' ' + wireY + ' ' + (cx - 4) + ' ' + (wireY + half), fill: 'none', stroke: LAD.INK, 'stroke-width': 1.6 }));
                g.appendChild(svgEl('path', { d: 'M ' + (cx + 4) + ' ' + (wireY - half) + ' Q ' + (cx + 12) + ' ' + wireY + ' ' + (cx + 4) + ' ' + (wireY + half), fill: 'none', stroke: LAD.INK, 'stroke-width': 1.6 }));
                if (el.g === 'otl') ladText(g, cx, wireY, 'L', LAD.INK, 'middle', 10, { bold: true });
                if (el.g === 'otu') ladText(g, cx, wireY, 'U', LAD.INK, 'middle', 10, { bold: true });
            }
/*I18N-BI-START*/
            const title = svgEl('title'); title.textContent = pickLang(el.tip) || ''; g.appendChild(title);
/*I18N-BI-END*/
/*I18N-BASE-START*/
            const title = svgEl('title'); title.textContent = el.tip || ''; g.appendChild(title);
/*I18N-BASE-END*/
        }
        function ladSeg(g, x1, y1, x2, y2, w) {
            g.appendChild(svgEl('line', { x1: x1, y1: y1, x2: x2, y2: y2,
                stroke: LAD.INK, 'stroke-width': w || 1.6, 'stroke-linecap': 'round' }));
        }
        function ladDrawBlock(g, x, wireY, w, blockH, headH, labelColW, el) {
            const top = wireY - blockH / 2;
            ladLine(g, x - 1, wireY, x, wireY);                 // entry stub
            ladLine(g, x + w, wireY, x + w + 1, wireY);         // exit stub
/*I18N-BI-START*/
            const blockDesc = pickLang(el.desc);
            if (blockDesc) ladDescText(g, x, top - 8, blockDesc);
/*I18N-BI-END*/
/*I18N-BASE-START*/
            if (el.desc) ladDescText(g, x, top - 8, el.desc);
/*I18N-BASE-END*/
            g.appendChild(svgEl('rect', { x: x, y: top, width: w, height: blockH, fill: '#ffffff', stroke: LAD.INK, 'stroke-width': 1.2, rx: 1 }));
            g.appendChild(svgEl('rect', { x: x, y: top, width: w, height: headH, fill: LAD.HEADBG, stroke: LAD.INK, 'stroke-width': 1.2 }));
/*I18N-BI-START*/
            ladText(g, x + w / 2, top + (el.sub ? 10 : headH / 2), pickLang(el.head), LAD.INK, 'middle', 12, { bold: true });
/*I18N-BI-END*/
/*I18N-BASE-START*/
            ladText(g, x + w / 2, top + (el.sub ? 10 : headH / 2), el.head, LAD.INK, 'middle', 12, { bold: true });
/*I18N-BASE-END*/
            if (el.sub) ladText(g, x + w / 2, top + headH - 6, el.sub, LAD.LABEL, 'middle', 9, { italic: true });
            let ry = top + headH;
            (el.rows || []).forEach(function (row) {
                const cy = ry + LAD.ROWH / 2;
                if (row.length === 2) {
                    ladText(g, x + LAD.PADX + labelColW, cy, row[0][0], LAD.LABEL, 'end', 11);
                    ladText(g, x + LAD.PADX + labelColW + 12, cy, row[1][0], ladCellColor(row[1][1]), 'start', 12, { tag: row[1][1] === 'tag' });
                } else {
                    ladText(g, x + LAD.PADX, cy, row[0][0], ladCellColor(row[0][1]), 'start', 12, { tag: row[0][1] === 'tag' });
                }
                ry += LAD.ROWH;
            });
/*I18N-BI-START*/
            const title = svgEl('title'); title.textContent = pickLang(el.tip) || ''; g.appendChild(title);
/*I18N-BI-END*/
/*I18N-BASE-START*/
            const title = svgEl('title'); title.textContent = el.tip || ''; g.appendChild(title);
/*I18N-BASE-END*/
        }

        // --- Top-level: build the <svg> for a rung model into `container` ---
        function renderLadder(container, model) {
            container.innerHTML = '';
            container.style.overflowX = 'auto';
            const inner = ladMeasureSeries(model.s ? model.s.s : []);
            const outs = (model.out || []).map(ladMeasureEl);
            let oyps = [], oUp = 0, oDown = 0, maxOutW = 0;
            if (outs.length) {
                oyps[0] = 0; let bottom = outs[0].down; oUp = outs[0].up;
                for (let i = 1; i < outs.length; i++) {
                    oyps[i] = bottom + LAD.VGAP + outs[i].up; bottom = oyps[i] + outs[i].down;
                }
                oDown = bottom;
                maxOutW = Math.max.apply(null, outs.map(function (o) { return o.w; }));
            }
            const up = Math.max(inner.up, oUp, LAD.GLYPHH / 2);
            const down = Math.max(inner.down, oDown, LAD.GLYPHH / 2);
            const wireY = LAD.TOP + up;
            const H = Math.ceil(LAD.TOP + up + down + LAD.BOT);

            const leftX = LAD.RAILW;
            const inStartX = leftX + LAD.GUT;
            const inRight = inStartX + inner.w;
            let needW = inRight + LAD.GUT;
            if (outs.length) needW = inRight + LAD.MINGAP + maxOutW + LAD.GUT * 2;

            // Layout happens in logical units; the whole SVG is then displayed
            // scaled up by LAD_ZOOM so the text reads comfortably. Available width
            // is divided by the zoom so the rail still lands on the container edge.
            const cs = getComputedStyle(container);
            const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
            const availW = Math.max(((container.clientWidth || 1) - pad) / LAD_ZOOM, 120);
            const W = Math.ceil(Math.max(availW, needW));
            const rightX = W - LAD.RAILW;
            _ladCurW = W;

            const svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H,
                width: Math.round(W * LAD_ZOOM), height: Math.round(H * LAD_ZOOM) });
            svg.style.maxWidth = 'none'; svg.style.display = 'block';
            const g = svgEl('g'); svg.appendChild(g);
            // Power rails
            g.appendChild(svgEl('line', { x1: leftX, y1: 0, x2: leftX, y2: H, stroke: LAD.RAIL, 'stroke-width': LAD.RAILW + 1 }));
            g.appendChild(svgEl('line', { x1: rightX, y1: 0, x2: rightX, y2: H, stroke: LAD.RAIL, 'stroke-width': LAD.RAILW + 1 }));
            ladLine(g, leftX, wireY, inStartX, wireY);
            inner.draw(g, inStartX, wireY);
            if (outs.length) {
                const outRight = rightX - LAD.GUT;
                const joinX = outRight - maxOutW;
                ladLine(g, inRight, wireY, joinX, wireY);        // long flow wire
                if (outs.length > 1) ladLine(g, joinX, wireY + oyps[0], joinX, wireY + oyps[oyps.length - 1]);
                outs.forEach(function (o, i) {
                    const wy = wireY + oyps[i];
                    const ox = outRight - o.w;                    // right-justified
                    if (ox > joinX) ladLine(g, joinX, wy, ox, wy);
                    o.draw(g, ox, wy);
                    ladLine(g, ox + o.w, wy, rightX, wy);
                });
            } else {
                ladLine(g, inRight, wireY, rightX, wireY);
            }
            container.appendChild(svg);
            return svg;
        }

        function renderSingleLadder(container) {
            const key = container.dataset.rungKey;
            if (!key || container.dataset.rendered === 'true') return;
            const model = rungData[key];
            if (!model) {
                container.innerHTML = '<span style="color:#999;font-style:italic;">Diagram unavailable</span>';
                container.dataset.rendered = 'true';
                return;
            }
            try {
                renderLadder(container, model);
                container._ladModel = model;
                container._ladW = Math.round(container.clientWidth);
                container.dataset.rendered = 'true';
                ladderResizeObserver.observe(container);
                if (colorizeOn) colorizeContainer(container);
                if (typeof scheduleMinimapRebuild === 'function') scheduleMinimapRebuild();
            } catch (e) {
                container.innerHTML = '<span style="color:#999;font-style:italic;">Diagram error: ' + e.message + '</span>';
                container.dataset.rendered = 'true';
            }
        }

        // Re-render a rung when its container's width actually changes (sidebar
        // toggle, window resize). Width is the only trigger; ignore height-only
        // changes (our own render alters svg height and would otherwise loop).
        const ladderResizeObserver = new ResizeObserver(function (entries) {
            entries.forEach(function (entry) {
                const c = entry.target;
                if (c.dataset.rendered !== 'true' || !c._ladModel) return;
                const w = Math.round(entry.contentRect.width);
                if (!w || c._ladW === w) return;
                c._ladW = w;
                try { renderLadder(c, c._ladModel); if (colorizeOn) colorizeContainer(c); } catch (e) {}
                if (typeof scheduleMinimapRebuild === 'function') scheduleMinimapRebuild();
            });
        });

