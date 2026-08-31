        // Tag usage data
        const tagData = window.__LADDER_DATA__.tagData;

        // Routine index for the global jump box
        const routineIndex = window.__LADDER_DATA__.routineIndex;

        // Rung DOT data for ladder visualization
        const rungData = window.__LADDER_DATA__.rungData;

        // Network tree data for interactive diagram
        const networkTree = window.__LADDER_DATA__.networkTree;
        
        // Current graphviz instance
        let graphviz = null;
        let currentZoom = 1;
        
