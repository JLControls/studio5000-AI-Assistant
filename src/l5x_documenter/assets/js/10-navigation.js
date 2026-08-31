        // Navigation backed by the browser History API, so the native Back/Forward
        // buttons work as well as the in-page arrows. The URL hash mirrors the
        // active section, so links, refresh and bookmarks restore the view too.
        let suppressHistory = false;

        function navigateBack() { history.back(); }
        function navigateForward() { history.forward(); }

        // The History API exposes no stack length, so we can't reliably grey out
        // the arrows at the ends - keep them enabled.
        function updateNavButtons() {
            const backBtn = document.getElementById('btn-back');
            const fwdBtn = document.getElementById('btn-forward');
            if (backBtn) backBtn.disabled = false;
            if (fwdBtn) fwdBtn.disabled = false;
        }

        // Restore the view when the user uses the browser Back/Forward buttons.
        window.addEventListener('popstate', function (e) {
            const st = e.state;
            suppressHistory = true;
            const id = (st && st.sectionId)
                || (location.hash ? decodeURIComponent(location.hash.slice(1)) : 'overview');
            if (document.getElementById(id)) showSection(id, true);
            if (st && st.rungId) {
                setTimeout(function () {
                    const el = document.getElementById(st.rungId);
                    if (el) el.scrollIntoView({ behavior: 'instant', block: 'center' });
                }, 60);
            }
            suppressHistory = false;
        });

        // Handle a hash typed directly into the address bar.
        window.addEventListener('hashchange', function () {
            const id = location.hash ? decodeURIComponent(location.hash.slice(1)) : 'overview';
            const el = document.getElementById(id);
            if (el && !el.classList.contains('active')) showSection(id, true);
        });
        
        // Show section (skipHistory=true when restoring navigation)
        function showSection(id, skipHistory) {
            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            const target = document.getElementById(id);
            if (target) {
                target.classList.add('active');
            }
            
            // Mirror the active section in the URL via the History API so the
            // browser Back/Forward buttons (and refresh/bookmarks) work.
            if (!skipHistory && !suppressHistory) {
                history.pushState({ sectionId: id }, '', '#' + encodeURIComponent(id));
                updateNavButtons();
            }
            
            // Auto-expand the owning sidebar group + tree item (robust to layout).
            if (target && (id.startsWith('program-') || id.startsWith('routine-'))) {
                expandNavGroup('Programs');
                // Expand the program's tree item so the active routine is visible.
                let treeLink = document.querySelector('a[href="#' + id + '"]');
                if (!treeLink && id.startsWith('routine-')) {
                    const progSec = target.dataset.programSection;
                    if (progSec) treeLink = document.querySelector('a[href="#' + progSec + '"]');
                }
                const tree = treeLink ? treeLink.closest('.tree-item') : null;
                if (tree) tree.classList.add('expanded');
                highlightNavActive(id, tree);
            } else if (target && id.startsWith('aoi-')) {
                expandNavGroup('Add-On Instructions');
                highlightNavActive(id, null);
            } else {
                highlightNavActive(id, null);
            }

            // Keep the breadcrumb in sync (routine-aware callers set it after).
            if (typeof setCrumbs === 'function') setCrumbs(id, null);
            window.scrollTo({ top: 0, behavior: 'instant' });
            if (typeof buildMinimap === 'function') { buildMinimap(); setTimeout(buildMinimap, 120); }

            // Populate the per-routine tag browser (resets Colorize for the new routine).
            if (target && id.startsWith('routine-') && typeof buildTagBrowser === 'function') {
                buildTagBrowser(target);
            }

            // Render inline ladders (custom SVG renderer - no async engine to wait on)
            setTimeout(renderInlineLadders, 0);
        }

        // Filter tags
        function filterTags() {
            const search = document.getElementById('tag-search').value.toLowerCase();
            const scope = document.getElementById('scope-filter').value;
            const usageType = document.getElementById('usage-filter').value;
            
            document.querySelectorAll('#tag-table tbody tr').forEach(row => {
                const name = row.cells[0].textContent.toLowerCase();
                const rowScope = row.cells[2].textContent;
                const tagName = row.cells[0].textContent;
                
                const matchesSearch = name.includes(search);
                const matchesScope = !scope || rowScope === scope;
                
                // Check usage type filter
                let matchesUsage = true;
                if (usageType) {
                    const tag = tagData.find(t => t.name === tagName);
                    if (tag) {
                        matchesUsage = tag.usages.some(u => u.type === usageType);
                    } else {
                        matchesUsage = false;
                    }
                }
                
                row.classList.toggle('hidden', !(matchesSearch && matchesScope && matchesUsage));
            });
        }
        
        // Filter I/O Points
        function filterIOPoints() {
            const search = document.getElementById('io-search').value.toLowerCase();
            const ioType = document.getElementById('io-type-filter').value;
            const usageFilter = document.getElementById('io-usage-filter')?.value || '';
            
            document.querySelectorAll('.io-points-table tbody tr').forEach(row => {
                if (row.cells.length < 4) return;
                const module = row.cells[0].textContent.toLowerCase();
                const point = row.cells[1].textContent.toLowerCase();
                const tag = row.cells[3].textContent.toLowerCase();
                const desc = row.cells[4]?.textContent.toLowerCase() || '';
                const rowType = row.dataset.ioType;
                const isSpare = row.dataset.spare === 'true';
                
                const matchesSearch = module.includes(search) || 
                    point.includes(search) || tag.includes(search) || 
                    desc.includes(search);
                const matchesType = !ioType || rowType === ioType;
                const matchesUsage = !usageFilter || 
                    (usageFilter === 'spare' && isSpare) || 
                    (usageFilter === 'used' && !isSpare);
                
                row.classList.toggle('hidden', !(matchesSearch && matchesType && matchesUsage));
            });
        }
        
        // Show I/O point cross-reference
        function showIOPointXref(tagRef, moduleName, pointNum, pointType) {
            // Search for usages of this IO point in logic
            const usages = [];
            
            // Search through tag usages for this IO reference
            tagData.forEach(tag => {
                tag.usages.forEach(u => {
                    // Check if any rung references this IO point
                    const rungKey = u.program + '_' + u.routine + '_' + u.rung;
                    const dot = JSON.stringify(rungData[rungKey] || '');
                    if (dot.includes(tagRef) || dot.includes(moduleName)) {
                        usages.push({
                            program: u.program,
                            routine: u.routine,
                            rung: u.rung,
                            type: pointType === 'Input' ? 'read' : 'destructive',
                            instruction: u.instruction
                        });
                    }
                });
            });
            
            currentTagUsages = usages;
            currentUsageFilter = '';
            currentTagDescription = 'I/O Point: ' + tagRef;
            document.getElementById('modal-title').textContent = 'Cross-Reference: ' + tagRef;
            renderUsageList();
            document.getElementById('usage-modal').classList.add('active');
        }
        
        // Filter Alarms
        function filterAlarms() {
            const search = document.getElementById('alarm-search').value.toLowerCase();
            
            document.querySelectorAll('#alarm-table tbody tr').forEach(row => {
                if (row.cells.length < 3) return; // Skip empty/message rows
                const name = row.cells[0].textContent.toLowerCase();
                const type = row.cells[1].textContent.toLowerCase();
                const desc = row.cells[2].textContent.toLowerCase();
                
                const matchesSearch = name.includes(search) || type.includes(search) || desc.includes(search);
                
                row.classList.toggle('hidden', !matchesSearch);
            });
        }
        
        // Sort table
        function sortTable(tableId, column) {
            const table = document.getElementById(tableId);
            const rows = Array.from(table.querySelectorAll('tbody tr'));
            const isAsc = table.dataset.sortCol === String(column) && table.dataset.sortDir === 'asc';
            
            rows.sort((a, b) => {
                const aVal = a.cells[column].textContent;
                const bVal = b.cells[column].textContent;
                return isAsc ? bVal.localeCompare(aVal) : aVal.localeCompare(bVal);
            });
            
            rows.forEach(row => table.querySelector('tbody').appendChild(row));
            
            table.dataset.sortCol = column;
            table.dataset.sortDir = isAsc ? 'desc' : 'asc';
        }
        
        // Tree view toggle
        function toggleTree(header) {
            const item = header.closest('.tree-item');
            item.classList.toggle('expanded');
        }
        
        // Navigate to section and scroll to routine
        function showSectionAndRoutine(sectionId, routineName) {
            showSection(sectionId);
            setCrumbs(sectionId, routineName);
            setTimeout(() => {
                const routineHeaders = document.querySelectorAll('#' + sectionId + ' .routine-header h4');
                for (const header of routineHeaders) {
                    if (header.textContent.includes(routineName)) {
                        header.closest('.routine-container').scrollIntoView({ behavior: 'smooth', block: 'start' });
                        break;
                    }
                }
            }, 150);
        }

        // ---- Breadcrumb ----------------------------------------------------
        let crumbState = { sectionId: 'overview', routine: null };

        function setCrumbs(sectionId, routineName) {
            crumbState.sectionId = sectionId;
            crumbState.routine = routineName || null;
            const el = document.getElementById('crumbs');
            if (!el) return;
            const ctl = (document.querySelector('.sidebar-header h1')?.textContent || '').trim();
            const sep = '<span class="crumb-sep">/</span>';
            const parts = ['<a class="crumb" onclick="showSection(\'overview\')">' + esc(ctl) + '</a>'];
            const sec = document.getElementById(sectionId);
            if (sectionId.startsWith('routine-')) {
                // Routine page: Controller / Programs / <program> / <routine>
/*I18N-BI-START*/
                const progSec = sec?.dataset.programSection || '';
                // `data-program`/`data-routine` hold the raw (possibly Italian)
                // identifier regardless of the active language - read the
                // display text from the sidebar tree links instead, which are
                // already bilingual (`.i18n-id` spans updated by
                // updateI18nSpans()), so the breadcrumb follows the toggle too.
                const progLink = progSec ? document.querySelector('a[href="#' + progSec + '"]') : null;
                const routLink = document.querySelector('a[href="#' + sectionId + '"]');
                const prog = (progLink ? progLink.textContent : (sec?.dataset.program || '')).trim();
                const rout = (routLink ? routLink.textContent : (sec?.dataset.routine || '')).trim();
/*I18N-BI-END*/
/*I18N-BASE-START*/
                const prog = sec?.dataset.program || '';
                const rout = sec?.dataset.routine || '';
                const progSec = sec?.dataset.programSection || '';
/*I18N-BASE-END*/
                parts.push('<span class="crumb-grp">Programs</span>');
                parts.push('<a class="crumb" onclick="showSection(\'' + progSec + '\')">' + esc(prog) + '</a>');
                parts.push('<span class="crumb-cur">' + esc(rout) + '</span>');
                el.innerHTML = parts.join(sep);
                return;
            }
            let group = '', leaf = '';
            const title = sec?.querySelector('h2')?.textContent.trim() || sectionId;
            if (sectionId.startsWith('program-')) { group = 'Programs'; leaf = title; }
            else if (sectionId.startsWith('aoi-')) { group = 'Add-On Instructions'; leaf = title; }
            else { leaf = title; }
            if (group) parts.push('<span class="crumb-grp">' + esc(group) + '</span>');
            if (routineName) {
                parts.push('<a class="crumb" onclick="showSection(\'' + sectionId + '\')">' + esc(leaf) + '</a>');
                parts.push('<span class="crumb-cur">' + esc(routineName) + '</span>');
            } else {
                parts.push('<span class="crumb-cur">' + esc(leaf) + '</span>');
            }
            el.innerHTML = parts.join(sep);
        }

        function esc(s) {
            return (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
        }

        function expandNavGroup(label) {
            document.querySelectorAll('.nav-section .project-nav-header').forEach(h => {
                if ((h.textContent || '').trim().includes(label)) {
                    h.classList.add('expanded');
                    h.classList.remove('collapsed');
                    const c = h.parentElement.querySelector('.project-nav-content');
                    if (c) c.classList.remove('collapsed');
                }
            });
        }

        function highlightNavActive(id) {
            document.querySelectorAll('.sidebar a.nav-active').forEach(a => a.classList.remove('nav-active'));
            const link = document.querySelector('.sidebar a[href="#' + id + '"]');
            if (link) link.classList.add('nav-active');
        }

        // ---- Sidebar filter ------------------------------------------------
        function filterNav(q) {
            q = (q || '').trim().toLowerCase();
            if (!q) { clearNavSearch(true); return; }
            // Program trees (with routine children)
            document.querySelectorAll('.tree-item').forEach(item => {
                const headA = item.querySelector(':scope > .tree-header a');
                const progName = headA ? headA.textContent.trim().toLowerCase() : '';
                const selfHit = progName.includes(q);
                let anyChild = false;
                item.querySelectorAll(':scope > .tree-children > li').forEach(li => {
                    const a = li.querySelector('a');
                    const name = a ? a.textContent.trim().toLowerCase() : '';
                    const hit = selfHit || name.includes(q);
                    li.classList.toggle('nav-hidden', !hit);
                    if (hit) anyChild = true;
                });
                const show = selfHit || anyChild;
                item.classList.toggle('nav-hidden', !show);
                item.classList.toggle('expanded', show);
            });
            // Flat lists (summary links, AOIs, equipment)
            document.querySelectorAll('.nav-section .project-nav-content > ul > li:not(.tree-item)').forEach(li => {
                const a = li.querySelector('a');
                const name = a ? a.textContent.trim().toLowerCase() : '';
                li.classList.toggle('nav-hidden', !name.includes(q));
            });
            // Expand every group so matches are visible
            document.querySelectorAll('.nav-section .project-nav-header').forEach(h => {
                h.classList.remove('collapsed'); h.classList.add('expanded');
                const c = h.parentElement.querySelector('.project-nav-content');
                if (c) c.classList.remove('collapsed');
            });
        }

        function clearNavSearch(keepValue) {
            if (!keepValue) {
                const inp = document.getElementById('nav-search');
                if (inp) inp.value = '';
            }
            document.querySelectorAll('.sidebar .nav-hidden').forEach(e => e.classList.remove('nav-hidden'));
        }

        // ---- Rung jump -----------------------------------------------------
        function flashRung(el) {
            if (!el) return;
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.classList.remove('rung-flash');
            void el.offsetWidth;
            el.classList.add('rung-flash');
            setTimeout(() => el.classList.remove('rung-flash'), 1500);
        }

        function jumpToRung(rungId) {
            flashRung(document.getElementById(rungId));
        }

        function jumpToRungNumber(val) {
            const n = (val || '').trim();
            if (!n) return;
            // Each routine is its own page, so the active section holds exactly the
            // rungs in scope - the match is unambiguous.
            const sec = document.querySelector('.section.active');
            if (!sec) return;
            for (const r of sec.querySelectorAll('.rung')) {
                const numEl = r.querySelector('.rung-number-col');
                if (numEl && numEl.textContent.trim() === n) { flashRung(r); return; }
            }
        }

        // ---- Global "go to" jump ------------------------------------------
        let gjResults = [];
        let gjActive = -1;

        function globalJump(q) {
            q = (q || '').trim().toLowerCase();
            const box = document.getElementById('global-jump-results');
            if (!q) { box.classList.remove('open'); box.innerHTML = ''; gjResults = []; return; }
            const tags = tagData
                .filter(t => t.name.toLowerCase().includes(q))
                .slice(0, 8)
                .map(t => ({ kind: 'tag', name: t.name, sub: t.dataType || '' }));
            const routines = routineIndex
                .filter(r => r.routine.toLowerCase().includes(q) || r.program.toLowerCase().includes(q))
                .slice(0, 8)
/*I18N-BI-START*/
                // Filter/lookup above uses the raw program/routine identifiers;
                // the visible jump-box text uses the bilingual display fields.
                .map(r => ({ kind: 'routine', name: pickLang(r.displayRoutine), sub: pickLang(r.displayProgram), section: r.section }));
/*I18N-BI-END*/
/*I18N-BASE-START*/
                .map(r => ({ kind: 'routine', name: r.routine, sub: r.program, section: r.section }));
/*I18N-BASE-END*/
            gjResults = routines.concat(tags);
            gjActive = gjResults.length ? 0 : -1;
            if (!gjResults.length) {
                box.innerHTML = '<div class="gj-empty">No tag or routine matches</div>';
                box.classList.add('open');
                return;
            }
            box.innerHTML = gjResults.map((r, i) =>
                '<div class="gj-item' + (i === gjActive ? ' active' : '') + '" data-i="' + i + '" ' +
                'onmousedown="gjPick(' + i + ')">' +
                '<span class="gj-kind ' + r.kind + '">' + r.kind + '</span>' +
                '<span class="gj-name">' + esc(r.name) + '</span>' +
                '<span class="gj-sub">' + esc(r.sub) + '</span></div>'
            ).join('');
            box.classList.add('open');
        }

        function gjPick(i) {
            const r = gjResults[i];
            if (!r) return;
            hideGlobalJump();
            const inp = document.getElementById('global-jump');
            if (inp) inp.value = '';
            if (r.kind === 'tag') { showUsages(r.name); }
            else { showSectionAndRoutine(r.section, r.name); }
        }

        function globalJumpKey(e) {
            const box = document.getElementById('global-jump-results');
            if (!gjResults.length) { if (e.key === 'Escape') hideGlobalJump(); return; }
            if (e.key === 'ArrowDown') { e.preventDefault(); gjActive = (gjActive + 1) % gjResults.length; gjPaint(); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); gjActive = (gjActive - 1 + gjResults.length) % gjResults.length; gjPaint(); }
            else if (e.key === 'Enter') { e.preventDefault(); if (gjActive >= 0) gjPick(gjActive); }
            else if (e.key === 'Escape') { hideGlobalJump(); }
        }

        function gjPaint() {
            document.querySelectorAll('#global-jump-results .gj-item').forEach(el => {
                el.classList.toggle('active', Number(el.dataset.i) === gjActive);
            });
        }

        function hideGlobalJump() {
            const box = document.getElementById('global-jump-results');
            if (box) box.classList.remove('open');
        }

        // ---- Floating routine minimap -------------------------------------
        let minimapSection = null;

        function absTop(el) {
            let y = 0;
            while (el) { y += el.offsetTop; el = el.offsetParent; }
            return y;
        }

        // Build a proportional render of the active routine page: one block per
        // rung, holding a tiny clone of that rung's actual ladder logic (squished
        // to fill the slot), with the current viewport overlaid. Rungs not yet
        // lazily rendered fall back to a faint numbered block until they load.
        function buildMinimap() {
            const sec = document.querySelector('.section.active');
            const isRoutine = !!(sec && sec.classList.contains('routine-page'));
            document.body.classList.toggle('minimap-on', isRoutine);
            const inner = document.getElementById('minimap-inner');
            if (!isRoutine || !inner) { minimapSection = null; if (inner) inner.innerHTML = ''; return; }
            const rungs = [...sec.querySelectorAll('.rung')];
            const track = document.getElementById('minimap-track');
            const trackH = track.clientHeight || 1;
            const docH = document.documentElement.scrollHeight || 1;
            // Never magnify: a short routine yields a short minimap, not a stretched
            // one. Thumbnails below preserve aspect ratio (no vertical stretch).
            const scale = Math.min(trackH / docH, 1);
            if (!rungs.length) { inner.innerHTML = ''; minimapSection = sec; updateMinimapViewport(); return; }
            inner.innerHTML = '';
            const frag = document.createDocumentFragment();
            rungs.forEach(r => {
                const top = absTop(r) * scale;
                const h = Math.max(r.offsetHeight * scale, 3);
                const block = document.createElement('div');
                block.className = 'mm-block' + (r.querySelector('.rung-comment') ? ' commented' : '');
                block.style.top = top.toFixed(1) + 'px';
                block.style.height = h.toFixed(1) + 'px';
                const svg = r.querySelector('.ladder-inline-container svg');
                if (svg && h > 4) {
                    const clone = svg.cloneNode(true);
                    clone.removeAttribute('width');
                    clone.removeAttribute('height');
                    clone.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                    clone.style.width = '100%';
                    clone.style.height = '100%';
                    clone.style.display = 'block';
                    clone.style.pointerEvents = 'none';
                    block.classList.add('mm-thumb');
                    block.appendChild(clone);
                } else {
                    const num = (r.querySelector('.rung-number-col')?.textContent || '').trim();
                    if (h > 9) {
                        const s = document.createElement('span');
                        s.className = 'mm-num';
                        s.textContent = num;
                        block.appendChild(s);
                    }
                }
                frag.appendChild(block);
            });
            inner.appendChild(frag);
            minimapSection = sec;
            updateMinimapViewport();
        }

        function updateMinimapViewport() {
            if (!minimapSection) return;
            const track = document.getElementById('minimap-track');
            const vp = document.getElementById('minimap-viewport');
            if (!track || !vp) return;
            const trackH = track.clientHeight || 1;
            const docH = document.documentElement.scrollHeight || 1;
            const scale = Math.min(trackH / docH, 1);   // match buildMinimap
            vp.style.top = (window.scrollY * scale) + 'px';
            vp.style.height = Math.max(window.innerHeight * scale, 10) + 'px';
        }

        function minimapScrollTo(clientY) {
            const track = document.getElementById('minimap-track');
            if (!track) return;
            const rect = track.getBoundingClientRect();
            const docH = document.documentElement.scrollHeight;
            const frac = Math.min(Math.max((clientY - rect.top) / rect.height, 0), 1);
            window.scrollTo({ top: frac * docH - window.innerHeight / 2, behavior: 'instant' });
        }

        let mmRebuildTimer = null;
        function scheduleMinimapRebuild() {
            clearTimeout(mmRebuildTimer);
            mmRebuildTimer = setTimeout(buildMinimap, 250);
        }

        function initMinimap() {
            const track = document.getElementById('minimap-track');
            if (!track) return;
            let dragging = false;
            track.addEventListener('mousedown', e => { dragging = true; minimapScrollTo(e.clientY); e.preventDefault(); });
            window.addEventListener('mousemove', e => { if (dragging) minimapScrollTo(e.clientY); });
            window.addEventListener('mouseup', () => { dragging = false; });
            let ticking = false;
            window.addEventListener('scroll', () => {
                if (ticking) return;
                ticking = true;
                requestAnimationFrame(() => { updateMinimapViewport(); ticking = false; });
            }, { passive: true });
            let rtimer = null;
            window.addEventListener('resize', () => { clearTimeout(rtimer); rtimer = setTimeout(buildMinimap, 150); });
        }

