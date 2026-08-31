        // Initial render on page load for visible section
        document.addEventListener('DOMContentLoaded', function() {
            // Restore sidebar collapse state
            if (localStorage.getItem('sidebarCollapsed') === 'true') {
                const sidebar = document.querySelector('.sidebar');
                sidebar.classList.add('collapsed');
            }
            
            // Establish a base history entry and restore any section named in the
            // URL hash (deep link / refresh) before rendering.
            const hashId = location.hash ? decodeURIComponent(location.hash.slice(1)) : '';
            const initId = (hashId && document.getElementById(hashId)) ? hashId : 'overview';
            if (initId !== 'overview') showSection(initId, true);
            history.replaceState({ sectionId: initId }, '', '#' + encodeURIComponent(initId));
            updateNavButtons();

            renderNetworkDiagram();
            renderInlineLadders();
            initMinimap();
            buildMinimap();
/*I18N-BI-START*/

            // Bilingual toggle: no-op on a non-bilingual page (no #lang-toggle).
            // Run after the initial renders above so setLang()'s re-render (via
            // rerenderForLang()) has something to re-render.
            if (typeof initI18n === 'function') initI18n();
/*I18N-BI-END*/
        });
        
        // Close modals on outside click
        window.onclick = function(event) {
            if (event.target.classList.contains('modal')) {
                event.target.classList.remove('active');
            }
        }
        
        // Keyboard shortcuts
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeModal();
                closeLadderModal();
            }
        });
        
