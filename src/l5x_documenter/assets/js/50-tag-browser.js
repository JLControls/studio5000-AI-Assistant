        // ===== Tag browser + Colorize =========================================
        // Lists every tag used in the active routine; Colorize assigns each a
        // distinct color and tints the components that reference it (a left-to-right
        // gradient when a component references several tags). Text stays on top so
        // it remains legible.
        let colorizeOn = false;
        let tagColorMap = {};      // base tag name -> color (for the active routine)
        let _ladGradSeq = 0;

        function ladTagColor(i, n) {
            const hue = Math.round((i * 360 / Math.max(n, 1)) % 360);
            return 'hsl(' + hue + ', 70%, 45%)';
        }

        // Collect {base: count} for every real tag referenced in a routine section.
        function collectRoutineTags(section) {
            const counts = {};
            const add = ref => {
                const base = (ref || '').split('.')[0].split('[')[0];
                if (base && tagData.some(td => td.name === base)) counts[base] = (counts[base] || 0) + 1;
            };
            const walkEl = e => {
                if (e.tag) add(e.tag);
                (e.rows || []).forEach(row => row.forEach(cell => { if (cell[1] === 'tag') add(cell[0]); }));
            };
            const walkSeries = s => (s && s.s ? s.s : []).forEach(it => {
                if (it.e) walkEl(it.e); else if (it.p) it.p.forEach(walkSeries);
            });
            section.querySelectorAll('.ladder-inline-container').forEach(c => {
                const m = rungData[c.dataset.rungKey];
                if (!m) return;
                walkSeries(m.s);
                (m.out || []).forEach(walkEl);
            });
            return Object.keys(counts).sort().map(base => ({ base: base, count: counts[base] }));
        }

        // The tag browser is a single floating panel (#tagbrowser, above the
        // minimap); it is repopulated for whichever routine is shown.
        function buildTagBrowser(section) {
            const aside = document.getElementById('tagbrowser');
            if (!aside) return;
            const list = aside.querySelector('.tb-list');
            const tags = collectRoutineTags(section);
            aside.querySelector('.tb-count').textContent = tags.length;
            tagColorMap = {};
            tags.forEach((t, i) => { tagColorMap[t.base] = ladTagColor(i, tags.length); });
            list.innerHTML = tags.map(t =>
                '<div class="tb-row" data-base="' + t.base + '">'
                + '<span class="tb-swatch" style="background:' + tagColorMap[t.base] + '"></span>'
                + '<span class="tb-name">' + t.base + '</span>'
                + '<span class="tb-ct">' + t.count + '</span></div>').join('');
            // Reset colorize when (re)building for a new routine.
            colorizeOn = false;
            const btn = aside.querySelector('.tb-colorize');
            if (btn) btn.classList.remove('active');
            list.classList.remove('tb-colored');
        }

        function toggleTagBrowser(btn) {
            const aside = btn.closest('.tag-browser');
            if (aside) aside.classList.toggle('collapsed');
        }

        function toggleColorize(btn) {
            const section = document.querySelector('.section.routine-page.active');
            if (!section) return;
            colorizeOn = !colorizeOn;
            btn.classList.toggle('active', colorizeOn);
            const list = document.querySelector('#tagbrowser .tb-list');
            if (list) list.classList.toggle('tb-colored', colorizeOn);
            section.querySelectorAll('.ladder-inline-container').forEach(c => {
                if (colorizeOn) colorizeContainer(c); else clearColorize(c);
            });
            // Re-clone the minimap so its thumbnails match the colorized logic.
            if (typeof buildMinimap === 'function') buildMinimap();
        }

        function clearColorize(container) {
            container.querySelectorAll('.lad-hl').forEach(e => e.remove());
            container.querySelectorAll('defs.lad-defs').forEach(e => e.remove());
        }

        // Tint each component in `container` by the colors of the tags it references.
        function colorizeContainer(container) {
            clearColorize(container);
            const svg = container.querySelector('svg');
            if (!svg) return;
            svg.querySelectorAll('.lad-comp[data-tags]').forEach(comp => {
                const cols = comp.getAttribute('data-tags').split('|')
                    .map(b => tagColorMap[b]).filter(Boolean);
                if (!cols.length) return;
                let bb;
                try { bb = comp.getBBox(); } catch (e) { return; }
                if (!bb.width) return;
                const rect = svgEl('rect', { 'class': 'lad-hl', x: bb.x - 3, y: bb.y - 3,
                    width: bb.width + 6, height: bb.height + 6, rx: 3,
                    'stroke-width': 2, 'fill-opacity': 0.16 });
                if (cols.length === 1) {
                    rect.setAttribute('fill', cols[0]);
                    rect.setAttribute('stroke', cols[0]);
                } else {
                    const id = 'ladgrad-' + (_ladGradSeq++);
                    let defs = svg.querySelector('defs.lad-defs');
                    if (!defs) { defs = svgEl('defs', { 'class': 'lad-defs' }); svg.insertBefore(defs, svg.firstChild); }
                    const grad = svgEl('linearGradient', { id: id, x1: '0', y1: '0', x2: '1', y2: '0' });
                    cols.forEach((c, i) => grad.appendChild(svgEl('stop',
                        { offset: (cols.length === 1 ? 0 : i / (cols.length - 1) * 100) + '%', 'stop-color': c })));
                    defs.appendChild(grad);
                    rect.setAttribute('fill', 'url(#' + id + ')');
                    rect.setAttribute('stroke', 'url(#' + id + ')');
                }
                comp.parentNode.insertBefore(rect, comp);   // behind the component
            });
        }
        
        function renderInlineLadders() {
            const containers = document.querySelectorAll('.ladder-inline-container:not([data-rendered]):not([data-rendering])');
            containers.forEach(container => {
                ladderObserver.observe(container);
            });
        }

        // Note: showSection is defined above with all features integrated

