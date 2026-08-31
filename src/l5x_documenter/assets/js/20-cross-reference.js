        // Show tag usages - handles both base tags and UDT members
        let currentTagUsages = [];
        let currentUsageFilter = '';
        let currentTagDescription = '';
        let currentTagBase = '';
        let currentMemberPath = '';
        let currentShowAllMembers = true;

        // Does a usage reference touch the cross-referenced member (or a nested
        // member/element under it)?
        function usageMatchesMember(u) {
            if (!currentMemberPath) return true;
            const r = u.ref || '';
            const dot = r.indexOf('.');
            const refMember = dot >= 0 ? r.substring(dot + 1) : '';
            return refMember === currentMemberPath
                || refMember.startsWith(currentMemberPath + '.')
                || refMember.startsWith(currentMemberPath + '[');
        }

        function setShowAllMembers(v) {
            currentShowAllMembers = v;
            renderUsageList();
        }

        function showUsages(tagName) {
            // Check if this is a member reference (e.g., "mtrConveyor.bAutoReq")
            const parts = tagName.split('.');
            const baseName = parts[0].split('[')[0]; // Remove array subscripts
            const memberPath = parts.slice(1).join('.'); // Member path after base tag
            
            // Find the base tag
            const tag = tagData.find(t => t.name === baseName);
            if (!tag) {
                alert('Tag not found: ' + tagName);
                return;
            }
            
            // Determine description - try member description first for UDT members
            let description = '';
            if (memberPath && tag.memberDescriptions) {
                // Try to find the member description
                const firstMember = memberPath.split('.')[0].split('[')[0];
/*I18N-BI-START*/
                description = pickLang(tag.memberDescriptions[firstMember]) || '';
/*I18N-BI-END*/
/*I18N-BASE-START*/
                description = tag.memberDescriptions[firstMember] || '';
/*I18N-BASE-END*/
            }
            if (!description) {
/*I18N-BI-START*/
                description = pickLang(tag.description) || '';
/*I18N-BI-END*/
/*I18N-BASE-START*/
                description = tag.description || '';
/*I18N-BASE-END*/
            }
            
            // Member-aware cross reference: when a UDT member was clicked, default
            // to that member's usages, with a toggle to show all members.
            currentTagBase = baseName;
            currentMemberPath = memberPath;          // '' when the base tag itself
            currentShowAllMembers = !memberPath;     // member-only by default
            currentTagUsages = tag.usages;
            currentUsageFilter = '';
            currentTagDescription = description;
            document.getElementById('modal-title').textContent = 'Usages of ' + tagName;
            if (tag.usages.length === 0) {
                document.getElementById('modal-body').innerHTML =
                    '<div class="gj-empty">No usages found for this tag.</div>';
            } else {
                renderUsageList();
            }
            document.getElementById('usage-modal').classList.add('active');
        }
        
        // Get description for a tag reference (handles UDT members)
        function getTagDescription(tagRef) {
            const parts = tagRef.split('.');
            const baseName = parts[0].split('[')[0];
            const memberPath = parts.slice(1);
            
            const tag = tagData.find(t => t.name === baseName);
            if (!tag) return '';
            
            // If accessing a member, try to get member description
            if (memberPath.length > 0 && tag.memberDescriptions) {
                const firstMember = memberPath[0].split('[')[0];
                if (tag.memberDescriptions[firstMember]) {
/*I18N-BI-START*/
                    return pickLang(tag.memberDescriptions[firstMember]);
/*I18N-BI-END*/
/*I18N-BASE-START*/
                    return tag.memberDescriptions[firstMember];
/*I18N-BASE-END*/
                }
            }
/*I18N-BI-START*/

            return pickLang(tag.description) || '';
/*I18N-BI-END*/
/*I18N-BASE-START*/
            
            return tag.description || '';
/*I18N-BASE-END*/
        }
        
        function filterUsages(type) {
            currentUsageFilter = type;
            renderUsageList();
        }
        
        function renderUsageList() {
            // 1) member scope, then 2) read/destructive type filter.
            const scoped = (currentMemberPath && !currentShowAllMembers)
                ? currentTagUsages.filter(usageMatchesMember)
                : currentTagUsages;
            const filtered = currentUsageFilter
                ? scoped.filter(u => u.type === currentUsageFilter)
                : scoped;

            let html = '';
            if (currentTagDescription) {
                html += `<div class="tag-description"><strong>Description:</strong> ${currentTagDescription}</div>`;
            }

            // Member scope toggle - only when a specific UDT member was referenced.
            if (currentMemberPath) {
                const memberCount = currentTagUsages.filter(usageMatchesMember).length;
                const allCount = currentTagUsages.length;
                html += `<div class="member-toggle-bar">
                    <span class="member-toggle-label">Scope</span>
                    <button class="usage-filter-btn ${currentShowAllMembers ? 'active' : ''}" onclick="setShowAllMembers(true)">All members of ${currentTagBase} (${allCount})</button>
                    <button class="usage-filter-btn ${!currentShowAllMembers ? 'active' : ''}" onclick="setShowAllMembers(false)">.${currentMemberPath} (${memberCount})</button>
                </div>`;
            }

            html += `<div class="usage-filter-bar">
                <button class="usage-filter-btn ${currentUsageFilter === '' ? 'active' : ''}" onclick="filterUsages('')">All (${scoped.length})</button>
                <button class="usage-filter-btn ${currentUsageFilter === 'read' ? 'active' : ''}" onclick="filterUsages('read')">Read (${scoped.filter(u => u.type === 'read').length})</button>
                <button class="usage-filter-btn ${currentUsageFilter === 'destructive' ? 'active' : ''}" onclick="filterUsages('destructive')">Destructive (${scoped.filter(u => u.type === 'destructive').length})</button>
            </div>`;
            
            html += '<div class="usage-list">';
            filtered.forEach(u => {
                const rungId = 'rung-' + u.program + '-' + u.routine + '-' + u.rung;
                const sectionId = u.program.startsWith('AOI_')
                    ? 'aoi-' + u.program.substring(4)
                    : 'routine-' + u.program + '-' + u.routine;
                const refHtml = u.ref ? `<code class="usage-ref">${esc(u.ref)}</code>` : '';
                html += `
                    <div class="usage-item clickable" onclick="navigateToRung('${sectionId}', '${rungId}')">
                        <div>
                            <strong>${u.program}</strong> → ${u.routine} → Rung ${u.rung}
                            <br><small>${u.instruction}</small> ${refHtml}
                        </div>
                        <span class="usage-type ${u.type}">${u.type}</span>
                    </div>
                `;
            });
            html += '</div>';
            
            document.getElementById('modal-body').innerHTML = html;
        }
        
        function navigateToRung(sectionId, rungId) {
            closeModal();
            // Full section setup without its own history push, then record one
            // combined section+rung entry so Back returns to the prior view.
            showSection(sectionId, true);
            if (!suppressHistory) {
                history.pushState({ sectionId: sectionId, rungId: rungId }, '', '#' + encodeURIComponent(sectionId));
                updateNavButtons();
            }

            setTimeout(() => {
                const rungEl = document.getElementById(rungId);
                if (rungEl) {
                    rungEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    rungEl.classList.add('highlight');
                    setTimeout(() => rungEl.classList.remove('highlight'), 2000);
                }
            }, 150);
        }
        
        // Navigate to a routine (used by JSR clicks) - each routine is its own page.
        function navigateToRoutine(programName, routineName) {
            const sectionId = 'routine-' + programName + '-' + routineName;
            if (document.getElementById(sectionId)) {
                showSection(sectionId);
            } else {
                // Fallback: program index page
                showSection('program-' + programName);
            }
        }
        
        // Close modal
        function closeModal() {
            document.getElementById('usage-modal').classList.remove('active');
        }
        
        // Show ladder diagram
        function showLadder(program, routine, rungNum) {
            const key = program + '_' + routine + '_' + rungNum;
            const model = rungData[key];

            if (!model) {
                alert('Could not generate ladder diagram for this rung.');
                return;
            }

            document.getElementById('ladder-modal-title').textContent =
                program + ' → ' + routine + ' → Rung ' + rungNum;
            document.getElementById('ladder-modal').classList.add('active');

            currentZoom = 1;
            const container = document.getElementById('ladder-container');
/*I18N-BI-START*/
            container._ladModel = model;   // lets rerenderForLang() redraw this on a language toggle
/*I18N-BI-END*/
            try {
                // Defer one frame so the modal has its final width before layout.
                requestAnimationFrame(function () { renderLadder(container, model); });
            } catch (e) {
                container.innerHTML = '<p style="color: red; padding: 20px;">Error rendering diagram: ' + e.message + '</p>';
            }
        }
        
        // Close ladder modal
        function closeLadderModal() {
            document.getElementById('ladder-modal').classList.remove('active');
        }
        
        // Zoom controls
        function zoomIn() {
            currentZoom *= 1.2;
            applyZoom();
        }
        
        function zoomOut() {
            currentZoom *= 0.8;
            applyZoom();
        }
        
        function resetZoom() {
            currentZoom = 1;
            applyZoom();
        }
        
        function applyZoom() {
            const svg = document.querySelector('#ladder-container svg');
            if (svg) {
                svg.style.transform = 'scale(' + currentZoom + ')';
                svg.style.transformOrigin = 'center center';
            }
        }
        
        // Render rung tag descriptions (if any)
        function renderRungDescriptions(container) {
            const rungDescDiv = container.closest('.rung')?.querySelector('.rung-tag-desc');
            if (rungDescDiv) {
                // Get all text nodes from the diagram
                // This is optional - descriptions may be populated from tag data
                // For now, leave as placeholder in case tag descriptions are added
            }
            // Add click handlers for tag cross-reference
            addTagClickHandlers(container);
        }
        
        // Render all rung descriptions on page
        function renderAllRungDescriptions() {
            document.querySelectorAll('.ladder-inline-container').forEach(container => {
                renderRungDescriptions(container);
            });
        }
        
        // Extract tag references from tooltip or text content
        function extractTagsFromElement(node) {
            const tags = [];
            const seen = new Set();
            
            // Get tooltip which contains full instruction
            const title = node.querySelector('title');
            let tooltip = title ? title.textContent.trim() : '';
            
            // Also get text content
            const texts = node.querySelectorAll('text');
            let textContent = '';
            texts.forEach(t => { textContent += ' ' + t.textContent; });
            
            // Parse instruction from tooltip: INSTR(operand1, operand2, ...)
            // Use a more flexible regex that handles nested parens and trailing chars
            const instrMatch = tooltip.match(/^([A-Z_][A-Z0-9_]*)\s*\((.+)\)/i);
            let instrName = '';
            let operands = [];
            
            if (instrMatch) {
                instrName = instrMatch[1].toUpperCase();
                // Split operands carefully, respecting nested parentheses
                const operandStr = instrMatch[2];
                let depth = 0;
                let current = '';
                for (let i = 0; i < operandStr.length; i++) {
                    const ch = operandStr[i];
                    if (ch === '(') depth++;
                    else if (ch === ')') depth--;
                    else if (ch === ',' && depth === 0) {
                        operands.push(current.trim());
                        current = '';
                        continue;
                    }
                    current += ch;
                }
                if (current.trim()) operands.push(current.trim());
            }
            
            // For each operand, extract tags
            operands.forEach((op, idx) => {
                if (!op) return;
                // Skip pure numeric values
                if (/^-?\d+(\.\d+)?$/.test(op)) return;
                
                // Extract base tag (before any dots or brackets)
                const baseName = op.split('.')[0].split('[')[0];
                if (!baseName || !/^[a-zA-Z_]/.test(baseName)) return;
                
                if (!seen.has(op)) {
                    seen.add(op);
                    tags.push({
                        full: op,
                        base: baseName,
                        isTimer: instrName === 'TON' || instrName === 'TOF' || instrName === 'RTO',
                        isCounter: instrName === 'CTU' || instrName === 'CTD',
                        isAOI: !['XIC','XIO','OTE','OTL','OTU','TON','TOF','RTO','CTU','CTD',
                                'ADD','SUB','MUL','DIV','MOV','EQU','NEQ','LES','GRT','GEQ',
                                'LEQ','CMP','JSR','RET','ONS','OSR','OSF','RES','CLR','COP',
                                'FLL','NOP','AFI','BTD','GSV','SSV','MSG'].includes(instrName) && idx === 0,
                        instr: instrName
                    });
                }
            });
            
            return { tags, instrName };
        }
        
        // Show tag selection popup for multi-tag elements
        function showTagSelectionPopup(tags, instrName, event) {
            // Remove any existing popup
            const existing = document.getElementById('tag-select-popup');
            if (existing) existing.remove();
            
            const popup = document.createElement('div');
            popup.id = 'tag-select-popup';
            popup.className = 'tag-select-popup';
            popup.innerHTML = `
                <div class="popup-header">Select tag to cross-reference:</div>
                <div class="popup-list"></div>
            `;
            
            const list = popup.querySelector('.popup-list');
            
            tags.forEach(tag => {
                const item = document.createElement('div');
                item.className = 'popup-item';
                item.textContent = tag.full;
                item.onclick = () => {
                    popup.remove();
                    showTagCrossReference(tag.base);
                };
                list.appendChild(item);
                
                // For timers/counters, add submembers
                if (tag.isTimer) {
                    ['.DN', '.EN', '.TT', '.ACC', '.PRE'].forEach(suffix => {
                        const sub = document.createElement('div');
                        sub.className = 'popup-item sub-item';
                        sub.textContent = tag.base + suffix;
                        sub.onclick = () => {
                            popup.remove();
                            showUsages(tag.base + suffix);
                        };
                        list.appendChild(sub);
                    });
                } else if (tag.isCounter) {
                    ['.DN', '.CU', '.CD', '.OV', '.UN', '.ACC', '.PRE'].forEach(suffix => {
                        const sub = document.createElement('div');
                        sub.className = 'popup-item sub-item';
                        sub.textContent = tag.base + suffix;
                        sub.onclick = () => {
                            popup.remove();
                            showUsages(tag.base + suffix);
                        };
                        list.appendChild(sub);
                    });
                } else if (tag.isAOI && instrName) {
                    // Add option to view AOI logic
                    const viewAOI = document.createElement('div');
                    viewAOI.className = 'popup-item aoi-item';
                    viewAOI.innerHTML = '<em>View ' + instrName + ' logic →</em>';
                    viewAOI.onclick = () => {
                        popup.remove();
                        showAOILogic(instrName);
                    };
                    list.appendChild(viewAOI);
                }
            });
            
            // Position popup near click
            popup.style.left = (event.pageX + 10) + 'px';
            popup.style.top = (event.pageY + 10) + 'px';
            document.body.appendChild(popup);
            
            // Close on click outside
            setTimeout(() => {
                document.addEventListener('click', function closePopup(e) {
                    if (!popup.contains(e.target)) {
                        popup.remove();
                        document.removeEventListener('click', closePopup);
                    }
                });
            }, 100);
        }
        
        // Show AOI logic section
        function showAOILogic(aoiName) {
            const sectionId = 'aoi-' + aoiName;
            const section = document.getElementById(sectionId);
            if (section) {
                showSection('aois');
                setTimeout(() => {
                    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 100);
            } else {
                alert('AOI "' + aoiName + '" not found in this project.');
            }
        }
        
        // Add click handlers for tag nodes to show cross-reference
        function addTagClickHandlers(container) {
            const svg = container.querySelector('svg');
            if (!svg) return;
            
            svg.querySelectorAll('g.node').forEach(node => {
                node.style.cursor = 'pointer';
                node.addEventListener('click', (e) => {
                    e.stopPropagation();
                    
                    const { tags, instrName } = extractTagsFromElement(node);
                    
                    // Handle JSR - navigate to the called routine's page
                    if (instrName === 'JSR' && tags.length > 0) {
                        const routineName = tags[0].full;
                        const rungEl = node.closest('.rung');
                        const sectionEl = rungEl ? rungEl.closest('.section') : null;
                        // Prefer a routine in the same program as the JSR.
                        let progSec = sectionEl ? sectionEl.dataset.programSection : '';
                        let progName = progSec ? progSec.substring(8) : '';
                        if (progName && document.getElementById('routine-' + progName + '-' + routineName)) {
                            navigateToRoutine(progName, routineName);
                            return;
                        }
                        // Otherwise find any routine page with this name.
                        const match = routineIndex.find(r => r.routine === routineName && r.kind === 'program');
                        if (match) { navigateToRoutine(match.program, routineName); return; }
                        alert('Routine "' + routineName + '" not found.');
                        return;
                    }
                    
                    if (tags.length === 0) {
                        return; // No tags found
                    } else if (tags.length === 1 && !tags[0].isTimer && !tags[0].isCounter && !tags[0].isAOI) {
                        // Single simple tag - go directly to cross-reference
                        showUsages(tags[0].base);
                    } else {
                        // Multiple tags or complex element - show selection popup
                        showTagSelectionPopup(tags, instrName, e);
                    }
                });
            });
        }
        
        // Show tag cross-reference modal (simplified - just call showUsages directly)
        function showTagCrossReference(tagName) {
            showUsages(tagName);
        }
        
        // Toggle sidebar collapse with diagram redraw
        function toggleSidebar() {
            const sidebar = document.querySelector('.sidebar');
            sidebar.classList.toggle('collapsed');
            localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
            
            // Listen for sidebar transition end and redraw network diagram
            sidebar.addEventListener('transitionend', function onTransitionEnd(e) {
                // Only respond to the width transition (not child transitions)
                if (e.propertyName === 'width' && e.target === sidebar) {
                    sidebar.removeEventListener('transitionend', onTransitionEnd);
                    // Force redraw of network diagram if visible
                    const networkDiagram = document.getElementById('network-diagram');
                    if (networkDiagram && networkDiagram.querySelector('svg')) {
                        renderNetworkDiagram();
                    }
                }
            });
        }
        
        function toggleProjectNav(header) {
            const content = header.nextElementSibling;
            const isCollapsed = content.classList.contains('collapsed');

            if (isCollapsed) {
                // Expand: prepare height for transition
                content.classList.remove('collapsed');
                header.classList.add('expanded');
                content.style.maxHeight = content.scrollHeight + 'px';
                // After transition, remove explicit maxHeight to accommodate further growth
                content.addEventListener('transitionend', function onExpand() {
                    content.style.maxHeight = 'none';
                    content.removeEventListener('transitionend', onExpand);
                }, { once: true });
            } else {
                // Collapse: set current height then transition to 0
                content.style.maxHeight = content.scrollHeight + 'px';
                // Force reflow to apply the height before collapsing
                void content.offsetHeight;
                content.style.maxHeight = '0px';
                content.classList.add('collapsed');
                header.classList.remove('expanded');
            }
        }
        
        // Toggle rung text visibility
        function toggleRungText(btn) {
            const rung = btn.closest('.rung');
            const textEl = rung.querySelector('.rung-text');
            const isHidden = textEl.classList.contains('hidden');
            textEl.classList.toggle('hidden');
            btn.innerHTML = isHidden ? '<svg class="icon"><use href="#mdi-eye-off"></use></svg>' : '<svg class="icon"><use href="#mdi-eye"></use></svg>';
        }

        const networkTypeColors = {
            controller: '#0d47a1',
            adapter: '#1565c0',
            io: '#00897b',
            input: '#2e7d32',
            output: '#f57c00',
            analog: '#5e35b1',
            drive: '#ef6c00',
            servo: '#d32f2f',
            hmi: '#6a1b9a',
            safety: '#c62828',
            switch: '#5d4037',
            device: '#455a64',
            group: '#607d8b',
            placeholder: '#607d8b'
        };

        const networkTypeIcons = {
            controller: 'mdi-monitor',
            adapter: 'mdi-network',
            io: 'mdi-wrench',
            input: 'mdi-network',
            output: 'mdi-network',
            analog: 'mdi-thermometer',
            drive: 'mdi-engine',
            servo: 'mdi-wrench',
            hmi: 'mdi-monitor',
            safety: 'mdi-alert',
            switch: 'mdi-network',
            device: 'mdi-folder',
            group: 'mdi-folder',
            placeholder: 'mdi-folder'
        };

        function netEscape(value) {
            return (value || '').replace(/[&<>"']/g, (m) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[m]));
        }

        function netChildCount(node) {
            return (node.children ? node.children.length : 0) + (node._children ? node._children.length : 0);
        }

        function collapseToDepth(node, depth) {
            if (!node) return;
            if (node.depth >= depth && node.children) {
                node._children = node.children;
                node.children = null;
            }
            (node.children || node._children || []).forEach((child) => collapseToDepth(child, depth));
        }

        function expandAll(node) {
            if (!node) return;
            if (node._children) {
                node.children = node._children;
                node._children = null;
            }
            (node.children || []).forEach(expandAll);
        }

        function linkPath(d) {
            return `M${d.source.y},${d.source.x}C${d.source.y},${(d.source.x + d.target.x) / 2} ${d.target.y},${(d.source.x + d.target.x) / 2} ${d.target.y},${d.target.x}`;
        }

        // Build compact node card with tooltip for details
        function buildNodeCard(d) {
            const type = d.data.device_type || 'device';
            const color = networkTypeColors[type] || networkTypeColors.device;
            const icon = networkTypeIcons[type] || networkTypeIcons.device;
            const badgeValue = netChildCount(d);
            const badgeHTML = badgeValue > 0 ? `<div class="net-badge-compact" style="background:${color}">${badgeValue}</div>` : '';
            
            // Build tooltip content with full details
            const ipText = (d.data.ips && d.data.ips.length) ? d.data.ips.join(' | ') : 'IP not configured';
            const catalogText = d.data.catalog || '';
            const edgeText = d.data.edge_label ? `via ${d.data.edge_label}` : '';
            const tooltipParts = [catalogText, ipText, edgeText].filter(Boolean);
            const tooltipText = tooltipParts.join('&#10;'); // &#10; is newline in title attribute
            
            // Compact card: small icon + name only, details in tooltip
            return `<div class="net-card-compact" style="border-color:${color}" title="${tooltipText}">
                        <svg class="icon icon-sm" style="color:${color};width:16px;height:16px;"><use href="#${icon}"></use></svg>
                        <div class="net-name-compact">${netEscape(d.data.name)}</div>
                        ${badgeHTML}
                    </div>`;
        }

        function wireNetworkControls(root, updateFn) {
            const expandBtn = document.getElementById('net-expand-all');
            const collapseBtn = document.getElementById('net-collapse-all');
            if (expandBtn) {
                expandBtn.onclick = () => {
                    expandAll(root);
                    updateFn(root);
                };
            }
            if (collapseBtn) {
                collapseBtn.onclick = () => {
                    collapseToDepth(root, 1);
                    updateFn(root);
                };
            }
        }

        // Smart collapse: expand only hub devices (adapters, switches, controller)
        // Collapse leaf nodes (IO modules, drives) by default
        function smartCollapseNode(node) {
            if (!node) return;
            const type = node.data.device_type || 'device';
            const hasChildren = (node.children && node.children.length > 0) || (node._children && node._children.length > 0);
            
            // Hub types that should be expanded: controller, adapter, switch
            const hubTypes = ['controller', 'adapter', 'switch', 'group'];
            const isHub = hubTypes.includes(type);
            
            if (node.children) {
                // Recursively process children first
                node.children.forEach(child => smartCollapseNode(child));
                
                // Collapse if NOT a hub type (leaf nodes like IO, drives, etc.)
                if (!isHub && hasChildren) {
                    node._children = node.children;
                    node.children = null;
                }
            } else if (node._children) {
                // Also process collapsed children
                node._children.forEach(child => smartCollapseNode(child));
            }
        }

        // Render network diagram with compact nodes
