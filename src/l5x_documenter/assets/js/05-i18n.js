        // ===== Bilingual (EN/IT) language toggle ===============================
        // Task 3 (html_generator.py) emits, ONLY for bilingual docs:
        //   - `.i18n` / `.i18n-id` <span data-en="…" data-it="…"> text nodes
        //   - {en,it} objects (instead of plain strings) for certain fields in
        //     window.__LADDER_DATA__ (tagData[].description/memberDescriptions,
        //     networkTree name/edge_label, routineIndex[].displayRoutine/
        //     displayProgram, rungData[*] element .desc/.tip/.head)
        //   - a data-lang attribute on the body element
        //   - a #lang-toggle control with two .lang-btn buttons
        // On a non-bilingual page none of the above exists: pickLang() passes a
        // plain string through unchanged and initI18n() is a no-op (no toggle).
        let currentLang = (window.localStorage && localStorage.getItem('l5xdoc.lang')) || 'en';

        // Accepts a plain string OR an {en,it} object - returns the active-
        // language string. A plain string passes through unchanged, so
        // non-bilingual pages are unaffected.
        function pickLang(field) {
            if (field && typeof field === 'object' && ('en' in field || 'it' in field)) {
                return field[currentLang] != null ? field[currentLang] : (field.en != null ? field.en : field.it);
            }
            return field;
        }

        // Swap the text of every static `.i18n`/`.i18n-id` span in the document
        // (tables, nav, rung comments, headings, etc.) to the active language.
        function updateI18nSpans() {
            document.querySelectorAll('.i18n, .i18n-id').forEach(function (el) {
                el.textContent = currentLang === 'it' ? el.dataset.it : el.dataset.en;
            });
        }

        function updateLangButtons() {
            document.querySelectorAll('#lang-toggle .lang-btn').forEach(function (b) {
                b.classList.toggle('active', b.dataset.lang === currentLang);
            });
        }

        // The ladder/network SVG text comes from data (rungData/networkTree via
        // pickLang()), not from `.i18n` spans, so swapping spans is NOT enough -
        // the renderers must be re-invoked so they re-read the data in the new
        // language. Re-use the exact code paths the app already renders with,
        // rather than duplicating any layout logic here.
        function rerenderForLang() {
            // (a) Network diagram - it fully rebuilds itself from `networkTree`
            // each call (clears its container first), so re-running it is safe.
            renderNetworkDiagram();

            // (b) Every ladder currently rendered on the page (per-routine inline
            // diagrams), re-run through the same renderLadder() entry point.
            document.querySelectorAll('.ladder-inline-container[data-rendered="true"]').forEach(function (c) {
                if (!c._ladModel) return;
                try {
                    renderLadder(c, c._ladModel);
                    if (colorizeOn) colorizeContainer(c);
                } catch (e) { /* leave prior render in place on error */ }
            });

            // The single-rung ladder modal (#ladder-container), if it is
            // currently showing a diagram.
            const modalContainer = document.getElementById('ladder-container');
            if (modalContainer && modalContainer._ladModel) {
                try { renderLadder(modalContainer, modalContainer._ladModel); } catch (e) { /* ignore */ }
            }

            // Minimap thumbnails are clones of the ladder SVGs above - rebuild
            // them so they match the new-language diagrams.
            if (typeof scheduleMinimapRebuild === 'function') scheduleMinimapRebuild();

            // The sticky breadcrumb bar is built from plain JS strings (not
            // `.i18n` spans) for the routine-page case, so re-run it for the
            // currently active section too.
            if (typeof setCrumbs === 'function' && typeof crumbState !== 'undefined') {
                setCrumbs(crumbState.sectionId, crumbState.routine);
            }
        }

        function setLang(lang) {
            if (lang !== 'en' && lang !== 'it') return;
            currentLang = lang;
            document.body.dataset.lang = lang;
            try { localStorage.setItem('l5xdoc.lang', lang); } catch (e) { /* storage unavailable */ }
            updateI18nSpans();
            updateLangButtons();
            rerenderForLang();
        }

        function initI18n() {
            const toggle = document.getElementById('lang-toggle');
            if (!toggle) return;                 // not a bilingual page - nothing to do
            toggle.querySelectorAll('.lang-btn').forEach(function (b) {
                b.addEventListener('click', function () { setLang(b.dataset.lang); });
            });
            setLang(currentLang);                // apply saved/default language (also fixes initial render)
        }
