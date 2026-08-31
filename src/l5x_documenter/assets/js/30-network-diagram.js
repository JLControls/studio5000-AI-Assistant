        function renderNetworkDiagram() {
            const container = document.getElementById('network-diagram');
            if (!container) return;

            container.innerHTML = '';
            
            // Set fixed height and position for the container
            container.style.height = '600px';
            container.style.border = '1px solid #ddd';
            container.style.borderRadius = '4px';
            container.style.position = 'relative';

            if (!networkTree || !networkTree.name) {
                container.innerHTML = '<span style="color: #999; font-style: italic;">Network diagram unavailable: no Ethernet modules were found.</span>';
                return;
            }
            
             // Add Controls UI via Overlay
            const controlsDiv = document.createElement('div');
            controlsDiv.id = 'net-controls-overlay';
            controlsDiv.style.position = 'absolute';
            controlsDiv.style.top = '10px';
            controlsDiv.style.right = '10px';
            controlsDiv.style.zIndex = '1000';
            controlsDiv.style.background = 'rgba(255, 255, 255, 0.95)';
            controlsDiv.style.padding = '12px';
            controlsDiv.style.borderRadius = '6px';
            controlsDiv.style.border = '1px solid #ccc';
            controlsDiv.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)';
            controlsDiv.style.fontFamily = 'Segoe UI, sans-serif';
            controlsDiv.style.fontSize = '12px';
            controlsDiv.style.minWidth = '140px';
            
            controlsDiv.innerHTML = `
                <div style="margin-bottom: 8px; font-weight: 700; color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px;">Display Options</div>
                <label style="display: flex; align-items: center; margin-bottom: 6px; cursor: pointer; color: #444;">
                    <input type="checkbox" id="net-toggle-ip" style="margin-right: 6px;"> Show IP Addresses
                </label>
                <label style="display: flex; align-items: center; margin-bottom: 8px; cursor: pointer; color: #444;">
                    <input type="checkbox" id="net-toggle-desc" style="margin-right: 6px;"> Show Descriptions
                </label>
                <div style="margin-top: 8px; border-top: 1px solid #eee; padding-top: 8px; display: flex; flex-direction: column; gap: 6px;">
                    <button id="net-btn-expand-all" style="padding: 4px 8px; cursor: pointer; background: #fff; border: 1px solid #ccc; border-radius: 3px;">Expand All</button>
                    <button id="net-btn-collapse-default" style="padding: 4px 8px; cursor: pointer; background: #fff; border: 1px solid #ccc; border-radius: 3px;">Default View</button>
                </div>
            `;
            container.appendChild(controlsDiv);
            
            // State
            let showIP = false;
            let showDesc = false;
            
            // Data Storage
            const fullNodes = new Map(); // id -> nodeData
            const fullEdges = [];        // Array of edge objects
            const collapsedNodeIds = new Set();
            
            // Traversal Helpers
            const seenIds = new Set();
            let uniqueCounter = 0;
            
            // Helper: Check for grandchildren (to set default collapse state)
            function hasGrandChildren(node) {
                const children = (node.children || []).concat(node._children || []);
                if (!children.length) return false;
                for (let child of children) {
                    const grandChildren = (child.children || []).concat(child._children || []);
                    if (grandChildren.length > 0) return true;
                }
                return false;
            }

            function traverse(node, level, parentId) {
                if (!node) return;
                
                // Ensure ID
                if (!node.id) node.id = 'n_' + (++uniqueCounter);
                
                // Avoid duplicates (cyclic or shared references)
                if (seenIds.has(node.id)) return;
                seenIds.add(node.id);
                
                // Access Properties
                // Note: using raw object properties, not d3 .data
                const type = node.device_type || 'device';
                const color = networkTypeColors[type] || networkTypeColors.device;
                const ip = (node.ips && node.ips.length) ? node.ips[0] : '';
/*I18N-BI-START*/
                const desc = pickLang(node.description) || '';

/*I18N-BI-END*/
/*I18N-BASE-START*/
                const desc = node.description || '';
                
/*I18N-BASE-END*/
                const children = (node.children || []).concat(node._children || []);
                const hasChildren = children.length > 0;
                
                // Default Collapse Logic:
                // "Collapse any nodes that do not have any grandchildren"
                // i.e. hide leaf groups (an adapter whose only children are I/O).
                // Never collapse the root/controller (level 0) - on a flat topology
                // (devices wired straight to the controller) that would hide every
                // device and leave just the PLC.
                if (level > 0 && hasChildren && !hasGrandChildren(node)) {
                    collapsedNodeIds.add(node.id);
                }
                
                fullNodes.set(node.id, {
                    id: node.id,
/*I18N-BI-START*/
                    baseLabel: pickLang(node.name),
/*I18N-BI-END*/
/*I18N-BASE-START*/
                    baseLabel: node.name,
/*I18N-BASE-END*/
                    ip: ip,
                    desc: desc,
                    type: type,
                    level: level,
                    color: color,
                    catalog: node.catalog || '',
                    hasChildren: hasChildren,
                    // Store children IDs for visibility traversal? 
                    // Actually we can infer from edges later, or store here.
                    // Storing here is safer 
                    children: children
                });
                
                if (parentId) {
/*I18N-BI-START*/
                    fullEdges.push({ from: parentId, to: node.id, label: pickLang(node.edge_label) || '' });
/*I18N-BI-END*/
/*I18N-BASE-START*/
                    fullEdges.push({ from: parentId, to: node.id, label: node.edge_label || '' });
/*I18N-BASE-END*/
                }
                
                children.forEach(child => traverse(child, level + 1, node.id));
            }
            
            // Build Graph Data
            traverse(networkTree, 0, null);
            
            // Vis.js DataSets
            const visNodes = new vis.DataSet([]);
            const visEdges = new vis.DataSet([]);
            
            // Update Function using BFS
            function updateVisibility() {
                const visibleNodeIds = new Set();
                const queue = [networkTree.id];
                visibleNodeIds.add(networkTree.id);
                
                // BFS to find all visible nodes
                // If a node is in queue, it is visible. 
                // If it is NOT collapsed, add its children to queue.
                let ptr = 0;
                while(ptr < queue.length) {
                    const pid = queue[ptr++];
                    
                    if (!collapsedNodeIds.has(pid)) {
                        // Find children. We can use fullEdges or the stored children reference.
                        // Using stored children is cleaner as it maintains tree order better.
                        const pNode = fullNodes.get(pid);
                        if (pNode && pNode.children) {
                            pNode.children.forEach(c => {
                                // Only add if we haven't seen it (though tree shouldn't have cycles)
                                if (!visibleNodeIds.has(c.id)) {
                                    visibleNodeIds.add(c.id);
                                    queue.push(c.id);
                                }
                            });
                        }
                    }
                }
                
                // Update VisNodes
                const nodesToAdd = [];
                fullNodes.forEach(node => {
                    if (visibleNodeIds.has(node.id)) {
                        // Label Formatting
                        let label = `<b>${node.baseLabel}</b>`;
                        if (showIP && node.ip) label += `
<i>${node.ip}</i>`;
                        if (showDesc && node.desc) label += `
<i>${node.desc}</i>`;
                        
                        // Tooltip
                        const title = `<b>${netEscape(node.baseLabel)}</b><br>${netEscape(node.desc)}<br>${node.ip}<br>${node.catalog}`;
                        
                        // Visual cues for collapse
                        const isCollapsed = collapsedNodeIds.has(node.id);
                        const canExpand = node.hasChildren;
                        
                        nodesToAdd.push({
                            id: node.id,
                            label: label,
                            title: title,
                            level: node.level,
                            group: node.type,
                            shape: 'box',
                            color: {
                                background: (canExpand && isCollapsed) ? '#eef2f5' : '#ffffff',
                                border: node.color
                            },
                            font: { multi: 'html', size: 14 },
                            margin: 10,
                            borderWidth: (canExpand && isCollapsed) ? 3 : 2,
                            shadow: true
                        });
                    }
                });
                
                // Update VisEdges (only if both nodes visible)
                const edgesToAdd = fullEdges
                    .filter(e => visibleNodeIds.has(e.from) && visibleNodeIds.has(e.to))
                    .map(e => ({
                        ...e,
                        arrows: 'to',
                        color: { color: '#ccc' },
                        width: 1.5,
                        smooth: { type: 'cubicBezier', forceDirection: 'vertical', roundness: 0.4 }
                    }));
                    
                visNodes.clear();
                visNodes.add(nodesToAdd);
                visEdges.clear();
                visEdges.add(edgesToAdd);
            }
            
            // Initial Option Config
            const options = {
                layout: {
                    hierarchical: {
                        direction: 'UD',
                        sortMethod: 'directed',
                        levelSeparation: 260,
                        nodeSpacing: 100, // Increased for multiline labels
                        treeSpacing: 100,
                        blockShifting: true,
                        parentCentralization: true
                    }
                },
                interaction: {
                    dragNodes: false,
                    dragView: true,
                    zoomView: true,
                    hover: true,
                    selectConnectedEdges: false
                },
                physics: { enabled: false }
            };
            
            // Create dedicated container for Vis.js
            const visContainer = document.createElement('div');
            visContainer.style.width = '100%';
            visContainer.style.height = '100%';
            container.appendChild(visContainer);

            // Re-append controls to ensure they are on top (though z-index handles it)
            // But wait, we already appended controlsDiv to 'container' earlier. 
            // If we don't clear container, we are fine.
            // But we need to make sure we don't init network on 'container' directly.
            
            const network = new vis.Network(visContainer, { nodes: visNodes, edges: visEdges }, options);
            
            // Click Handler (Expand/Collapse)
            network.on("click", function(params) {
                if (params.nodes.length === 1) {
                    const nodeId = params.nodes[0];
                    const node = fullNodes.get(nodeId);
                    if (node && node.hasChildren) {
                        if (collapsedNodeIds.has(nodeId)) {
                            collapsedNodeIds.delete(nodeId);
                        } else {
                            collapsedNodeIds.add(nodeId);
                        }
                        updateVisibility();
                         // Reset physics to re-layout gracefully? Or just let hierarchical handle it.
                         // Often handy to fit or release physics briefly
                         network.fit({ animation: true });
                    }
                }
            });
            
            // UI Event Listeners
            const toggleIP = document.getElementById('net-toggle-ip');
            if(toggleIP) {
                toggleIP.addEventListener('change', (e) => {
                    showIP = e.target.checked;
                    updateVisibility();
                });
            }
            
            const toggleDesc = document.getElementById('net-toggle-desc');
            if(toggleDesc) {
                toggleDesc.addEventListener('change', (e) => {
                    showDesc = e.target.checked;
                    updateVisibility();
                });
            }
            
            const btnExpand = document.getElementById('net-btn-expand-all');
            if(btnExpand) {
                btnExpand.addEventListener('click', () => {
                    collapsedNodeIds.clear();
                    updateVisibility();
                    network.fit({ animation: true });
                });
            }
            
            const btnDefault = document.getElementById('net-btn-collapse-default');
            if(btnDefault) {
                btnDefault.addEventListener('click', () => {
                    collapsedNodeIds.clear();
                    fullNodes.forEach(n => {
                        if (n.hasChildren && !hasGrandChildren(n)) {
                             collapsedNodeIds.add(n.id);
                        }
                    });
                    updateVisibility();
                    network.fit({ animation: true });
                });
            }
            
            // Initial Render
            updateVisibility();
            
            // One-time fit logic
            network.once("stabilizationIterationsDone", function() {
                network.fit({ animation: { duration: 1000, easingFunction: 'easeInOutQuad' } });
            });
        }// Intersection Observer for lazy rendering of ladder diagrams
        const ladderObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const container = entry.target;
                    renderSingleLadder(container);
                    observer.unobserve(container);
                }
            });
        }, {
            rootMargin: '500px 0px',
            threshold: 0.01
        });

