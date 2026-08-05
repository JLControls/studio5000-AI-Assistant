#!/usr/bin/env python3
"""
Root entry point for plc_comment_tools in studio5000-AI-Assistant repository.
"""

import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent / "sourceRepo" / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from tag_analyzer.plc_comment_tools import main

if __name__ == "__main__":
    main()
