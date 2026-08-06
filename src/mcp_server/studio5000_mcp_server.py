#!/usr/bin/env python3
"""
Studio 5000 Logix Designer Documentation MCP Server

This MCP server provides access to Studio 5000/Logix Designer instruction documentation,
making it easy to search for and retrieve information about PLC instructions, programming
syntax, and best practices directly within AI conversations.
"""

import asyncio
import json
import os
import re
import sys
import threading
import importlib.util
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import argparse
from dataclasses import dataclass

# Import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Handle relative import for cache_manager (works both as script and module)
try:
    from .cache_manager import shared_cache_manager
except ImportError:
    # Fallback for when run as script
    cache_manager_path = os.path.join(os.path.dirname(__file__), 'cache_manager.py')
    if os.path.exists(cache_manager_path):
        spec = importlib.util.spec_from_file_location("cache_manager", cache_manager_path)
        cache_manager_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cache_manager_module)
        shared_cache_manager = cache_manager_module.shared_cache_manager
    else:
        # Create a minimal fallback cache manager
        class MockCacheManager:
            def get_cache_statistics(self):
                return {'overall': {'total_requests': 0, 'total_hits': 0, 'overall_hit_rate': 0}}
            def get_cache_lock(self, name):
                import threading
                return threading.Lock()
            def is_cache_valid(self, files, max_age_days=30):
                return False
        shared_cache_manager = MockCacheManager()

from code_generator.l5x_generator import L5XGenerator, L5XProject, Program, Routine, LadderRung, create_motor_control_example
from ai_assistant.code_assistant import CodeAssistant
from ai_assistant.mcp_integration import create_mcp_integrated_assistant
SDK_ENABLED = os.environ.get("STUDIO5000_SDK_ENABLED", "false").lower() in {"1", "true", "yes"}
if SDK_ENABLED:
    from sdk_interface.studio5000_sdk import studio5000_sdk
    from sdk_documentation.mcp_sdk_integration import SDKMCPIntegration, SDKMCPTools
else:
    studio5000_sdk = None
    SDKMCPIntegration = None
    SDKMCPTools = None
from documentation.instruction_mcp_integration import InstructionMCPIntegration, InstructionMCPTools
from l5x_analyzer.l5x_mcp_integration import L5XSDKMCPIntegration, L5XMCPTools
from drawings_analyzer.pdf_mcp_integration import PDFMCPIntegration, PDFMCPTools
from tag_analyzer.tag_mcp_integration import TagMCPIntegration, TagMCPTools
from ignition_exporter.ignition_mcp_integration import IgnitionMCPIntegration

# MCP imports (we'll implement a simplified version)
class MCPServer:
    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.tools = {}
        self.resources = {}
    
    def add_tool(self, name: str, description: str, handler):
        self.tools[name] = {
            "name": name,
            "description": description,
            "handler": handler
        }
    
    def add_resource(self, uri: str, description: str, handler):
        self.resources[uri] = {
            "uri": uri,
            "description": description,
            "handler": handler
        }

@dataclass
class Instruction:
    """Represents a Studio 5000 instruction"""
    name: str
    category: str
    description: str
    file_path: str
    languages: List[str]
    syntax: Optional[str] = None
    parameters: Optional[List[Dict]] = None
    examples: Optional[str] = None

class Studio5000Parser:
    """Parses Studio 5000 HTML documentation"""
    
    def __init__(self, doc_root: str):
        self.doc_root = Path(doc_root)
        self.instructions = {}
        self.categories = {}
        
    def parse_main_index(self) -> Dict[str, Any]:
        """Parse the main instruction set index"""
        index_file = self.doc_root / "17691.htm"
        if not index_file.exists():
            raise FileNotFoundError(f"Main index file not found: {index_file}")
        
        with open(index_file, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
        
        categories = {}
        
        # Find instruction category links
        links = soup.find_all('a', href=re.compile(r'\d+\.htm'))
        for link in links:
            if 'Instructions' in link.get_text():
                category_name = link.get_text().strip()
                category_file = link.get('href')
                categories[category_name] = category_file
        
        self.categories = categories
        return categories
    
    def parse_instruction_file(self, file_path: str) -> Optional[Instruction]:
        """Parse an individual instruction file"""
        full_path = self.doc_root / file_path
        if not full_path.exists():
            return None
        
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
            
            # Extract title
            title_elem = soup.find('title')
            title = title_elem.get_text().strip() if title_elem else ""
            
            # Extract instruction name from title
            match = re.search(r'([A-Z]{2,}[A-Z0-9]*)', title)
            instruction_name = match.group(1) if match else ""
            
            # Extract breadcrumb for category
            breadcrumb = soup.find('p', class_='breadcrumbs')
            category = ""
            if breadcrumb:
                links = breadcrumb.find_all('a')
                for link in links:
                    if 'Instructions' in link.get_text():
                        category = link.get_text().strip()
                        break
            
            # Extract description from first paragraph
            content_section = soup.find('div', id='content_section')
            description = ""
            if content_section:
                first_p = content_section.find('p')
                if first_p:
                    description = first_p.get_text().strip()
            
            # Determine supported languages from icons
            languages = []
            img_tags = soup.find_all('img', src=re.compile(r'o151\d+\.jpg'))
            if img_tags:
                # Based on the pattern seen in the documentation
                if any('o15168.jpg' in img.get('src', '') for img in img_tags):
                    languages.append('Ladder Diagram')
                if any('o15169.jpg' in img.get('src', '') for img in img_tags):
                    languages.append('Function Block')
                if any('o15170.jpg' in img.get('src', '') for img in img_tags):
                    languages.append('Structured Text')
            
            return Instruction(
                name=instruction_name,
                category=category,
                description=description,
                file_path=file_path,
                languages=languages,
                syntax=self._extract_syntax(soup),
                parameters=self._extract_parameters(soup),
                examples=self._extract_examples(soup)
            )
        
        except Exception as e:
            import sys
            print(f"Error parsing {file_path}: {e}", file=sys.stderr)
            return None
    
    def _extract_syntax(self, soup) -> Optional[str]:
        """Extract syntax information from the HTML"""
        # Look for syntax tables or code blocks
        syntax_patterns = [
            'Syntax',
            'Parameters',
            'Operands'
        ]
        
        for pattern in syntax_patterns:
            heading = soup.find(lambda tag: tag.name in ['h1', 'h2', 'h3', 'h4'] and 
                              pattern.lower() in tag.get_text().lower())
            if heading:
                # Get the next table or paragraph
                next_elem = heading.find_next_sibling(['table', 'p', 'div'])
                if next_elem:
                    return next_elem.get_text().strip()
        
        return None
    
    def _extract_parameters(self, soup) -> Optional[List[Dict]]:
        """Extract parameter information"""
        parameters = []
        
        # Look for parameter tables
        tables = soup.find_all('table')
        for table in tables:
            headers = table.find_all('th')
            if len(headers) >= 2:
                header_texts = [th.get_text().strip().lower() for th in headers]
                if any('parameter' in h or 'operand' in h for h in header_texts):
                    rows = table.find_all('tr')[1:]  # Skip header row
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            param = {
                                'name': cells[0].get_text().strip(),
                                'description': cells[1].get_text().strip()
                            }
                            if len(cells) > 2:
                                param['type'] = cells[2].get_text().strip()
                            parameters.append(param)
        
        return parameters if parameters else None
    
    def _extract_examples(self, soup) -> Optional[str]:
        """Extract example information"""
        example_patterns = ['example', 'sample', 'usage']
        
        for pattern in example_patterns:
            heading = soup.find(lambda tag: tag.name in ['h1', 'h2', 'h3', 'h4'] and 
                              pattern.lower() in tag.get_text().lower())
            if heading:
                example_content = []
                current = heading.find_next_sibling()
                while current and current.name not in ['h1', 'h2', 'h3', 'h4']:
                    if current.name in ['p', 'pre', 'code', 'div']:
                        example_content.append(current.get_text().strip())
                    current = current.find_next_sibling()
                
                if example_content:
                    return '\n\n'.join(example_content)
        
        return None
    
    def build_instruction_index(self, force_rebuild: bool = False) -> Dict[str, Instruction]:
        """Build a comprehensive index of all instructions with disk caching and parallel processing"""
        import pickle
        from concurrent.futures import ThreadPoolExecutor

        cache_dir = Path.home() / ".cache" / "studio5000"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "instruction_index_cache.pkl"

        if not force_rebuild and cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    self.instructions = pickle.load(f)
                return self.instructions
            except Exception as e:
                import sys
                print(f"Warning: Failed to load instruction cache: {e}", file=sys.stderr)

        instructions = {}

        # Parse categories first
        try:
            self.parse_main_index()
        except Exception:
            pass

        # Collect target HTML file paths from main index links (17691.htm) if available
        target_file_names = set()
        index_file = self.doc_root / "17691.htm"
        if index_file.exists():
            try:
                with open(index_file, 'r', encoding='utf-8', errors='ignore') as f:
                    soup = BeautifulSoup(f.read(), 'html.parser')
                links = soup.find_all('a', href=re.compile(r'^\d+\.htm$'))
                for link in links:
                    target_file_names.add(link['href'])
            except Exception:
                pass

        if target_file_names:
            html_files = [self.doc_root / fname for fname in target_file_names if (self.doc_root / fname).exists()]
        else:
            html_files = list(self.doc_root.glob("*.htm"))

        def parse_file(html_file):
            return self.parse_instruction_file(html_file.name)

        with ThreadPoolExecutor(max_workers=16) as executor:
            results = executor.map(parse_file, html_files)
            for instruction in results:
                if instruction and instruction.name:
                    instructions[instruction.name.upper()] = instruction

        
        self.instructions = instructions

        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(instructions, f)
        except Exception as e:
            import sys
            print(f"Warning: Failed to save instruction cache: {e}", file=sys.stderr)

        return instructions


class Studio5000MCPServer:
    """MCP Server for Studio 5000 documentation with optimized lazy loading"""
    
    def __init__(self, doc_root: str):
        self.doc_root = doc_root
        self.parser = Studio5000Parser(doc_root)
        self.server = MCPServer("studio5000-ai-assistant", "2.0.0")
        self.instructions = {}
        
        # Initialize basic components immediately (lightweight)
        self.l5x_generator = L5XGenerator()
        self.code_assistant = CodeAssistant(mcp_server=self)
        self.enhanced_assistant = create_mcp_integrated_assistant(self)
        self.studio5000_sdk = studio5000_sdk
        
        # Shared sentence transformer model for all vector databases
        self._shared_model = None
        self._model_lock = threading.Lock()
        
        # Lazy initialization flags and cached integrations
        self._sdk_integration = None
        self._sdk_tools = None
        self._instruction_integration = None
        self._instruction_tools = None
        self._l5x_integration = None
        self._l5x_tools = None
        self._pdf_integration = None
        self._pdf_tools = None
        self._tag_integration = None
        self._tag_tools = None
        self._ignition_integration = None

        # Initialization locks for thread safety
        self._init_locks = {
            'sdk': threading.Lock(),
            'instruction': threading.Lock(),
            'l5x': threading.Lock(),
            'pdf': threading.Lock(),
            'tag': threading.Lock(),
            'ignition': threading.Lock()
        }
        
        # Fast basic initialization only - vector DBs loaded on demand
        self._initialize_basic()
    
    def _initialize_basic(self):
        """Fast basic initialization - only load instruction index, no vector DBs"""
        import sys
        print("Starting fast initialization...", file=sys.stderr)
        self.instructions = self.parser.build_instruction_index()
        print(f"✅ Basic initialization complete. {len(self.instructions)} instructions loaded.", file=sys.stderr)
        print("📚 Vector databases will load automatically when needed for semantic search.", file=sys.stderr)
        
        # Register all tools (lightweight operation)
        self._register_tools()
        print("🔧 MCP tools registered successfully", file=sys.stderr)
    
    def _get_shared_model(self):
        """Get shared sentence transformer model, initializing if needed"""
        if self._shared_model is None:
            with self._model_lock:
                if self._shared_model is None:  # Double-check pattern
                    try:
                        import sys
                        print("🔄 Loading shared sentence transformer model...", file=sys.stderr)
                        from sentence_transformers import SentenceTransformer
                        self._shared_model = SentenceTransformer('all-MiniLM-L6-v2')
                        print("✅ Shared model loaded successfully", file=sys.stderr)
                    except Exception as e:
                        print(f"❌ Failed to load shared model: {e}", file=sys.stderr)
                        self._shared_model = None
        return self._shared_model
    
    @property
    def sdk_integration(self):
        """Lazy-loaded SDK integration"""
        if not SDK_ENABLED:
            raise RuntimeError("Studio 5000 SDK integration is disabled")
        if self._sdk_integration is None:
            with self._init_locks['sdk']:
                if self._sdk_integration is None:
                    print("🔄 Initializing SDK documentation system...", file=sys.stderr)
                    self._sdk_integration = SDKMCPIntegration()
                    # Inject shared model and cache manager
                    if hasattr(self._sdk_integration, 'vector_db'):
                        if hasattr(self._sdk_integration.vector_db, 'model'):
                            self._sdk_integration.vector_db.model = self._get_shared_model()
                        # Inject shared cache manager for optimized caching
                        self._sdk_integration.vector_db.cache_manager = shared_cache_manager
                    print("✅ SDK system ready", file=sys.stderr)
        return self._sdk_integration
    
    @property 
    def sdk_tools(self):
        """Lazy-loaded SDK tools"""
        if not SDK_ENABLED:
            raise RuntimeError("Studio 5000 SDK integration is disabled")
        if self._sdk_tools is None:
            self._sdk_tools = SDKMCPTools(self.sdk_integration)
        return self._sdk_tools
    
    @property
    def instruction_integration(self):
        """Lazy-loaded instruction integration"""
        if self._instruction_integration is None:
            with self._init_locks['instruction']:
                if self._instruction_integration is None:
                    print("🔄 Initializing instruction documentation system...", file=sys.stderr)
                    self._instruction_integration = InstructionMCPIntegration()
                    # Inject shared model and cache manager
                    if hasattr(self._instruction_integration, 'vector_db'):
                        if hasattr(self._instruction_integration.vector_db, 'model'):
                            self._instruction_integration.vector_db.model = self._get_shared_model()
                        # Inject shared cache manager for optimized caching
                        self._instruction_integration.vector_db.cache_manager = shared_cache_manager
                    print("✅ Instruction system ready", file=sys.stderr)
        return self._instruction_integration
    
    @property
    def instruction_tools(self):
        """Lazy-loaded instruction tools"""
        if self._instruction_tools is None:
            self._instruction_tools = InstructionMCPTools(self.instruction_integration)
        return self._instruction_tools
    
    @property
    def l5x_integration(self):
        """Lazy-loaded L5X integration"""
        if self._l5x_integration is None:
            with self._init_locks['l5x']:
                if self._l5x_integration is None:
                    print("🔄 Initializing L5X analyzer system...", file=sys.stderr)
                    self._l5x_integration = L5XSDKMCPIntegration()
                    # Inject shared model and cache manager
                    if hasattr(self._l5x_integration, 'vector_db'):
                        if hasattr(self._l5x_integration.vector_db, 'model'):
                            self._l5x_integration.vector_db.model = self._get_shared_model()
                        # Inject shared cache manager for optimized caching
                        self._l5x_integration.vector_db.cache_manager = shared_cache_manager
                    print("✅ L5X system ready", file=sys.stderr)
        return self._l5x_integration
    
    @property
    def l5x_tools(self):
        """Lazy-loaded L5X tools"""
        if self._l5x_tools is None:
            self._l5x_tools = L5XMCPTools
        return self._l5x_tools
    
    @property
    def pdf_integration(self):
        """Lazy-loaded PDF integration"""
        if self._pdf_integration is None:
            with self._init_locks['pdf']:
                if self._pdf_integration is None:
                    print("🔄 Initializing PDF drawings analyzer system...", file=sys.stderr)
                    self._pdf_integration = PDFMCPIntegration()
                    # Inject shared model and cache manager
                    if hasattr(self._pdf_integration, 'vector_db'):
                        if hasattr(self._pdf_integration.vector_db, 'model'):
                            self._pdf_integration.vector_db.model = self._get_shared_model()
                        # Inject shared cache manager for optimized caching
                        self._pdf_integration.vector_db.cache_manager = shared_cache_manager
                    print("✅ PDF system ready", file=sys.stderr)
        return self._pdf_integration
    
    @property
    def pdf_tools(self):
        """Lazy-loaded PDF tools"""
        if self._pdf_tools is None:
            self._pdf_tools = PDFMCPTools
        return self._pdf_tools
    
    @property
    def tag_integration(self):
        """Lazy-loaded tag integration"""
        if self._tag_integration is None:
            with self._init_locks['tag']:
                if self._tag_integration is None:
                    print("🔄 Initializing tag analyzer system...", file=sys.stderr)
                    self._tag_integration = TagMCPIntegration()
                    # Inject shared model and cache manager
                    if hasattr(self._tag_integration, 'vector_db'):
                        if hasattr(self._tag_integration.vector_db, 'model'):
                            self._tag_integration.vector_db.model = self._get_shared_model()
                        # Inject shared cache manager for optimized caching
                        self._tag_integration.vector_db.cache_manager = shared_cache_manager
                    print("✅ Tag system ready", file=sys.stderr)
        return self._tag_integration
    
    @property
    def tag_tools(self):
        """Lazy-loaded tag tools"""
        if self._tag_tools is None:
            self._tag_tools = TagMCPTools
        return self._tag_tools

    @property
    def ignition_integration(self):
        """Lazy-loaded Ignition exporter integration (pure/offline engine)"""
        if self._ignition_integration is None:
            with self._init_locks['ignition']:
                if self._ignition_integration is None:
                    print("🔄 Initializing Ignition exporter...", file=sys.stderr)
                    self._ignition_integration = IgnitionMCPIntegration()
                    print("✅ Ignition exporter ready", file=sys.stderr)
        return self._ignition_integration
    
    async def _ensure_instruction_db_ready(self):
        """Ensure the instruction vector database is fully initialized"""
        # Trigger lazy loading by accessing the property
        _ = self.instruction_integration
        
        # Initialize with instructions if not already done
        if hasattr(self.instruction_integration, 'initialize'):
            try:
                await self.instruction_integration.initialize(self.instructions, force_rebuild=False)
            except Exception as e:
                print(f"Warning: Could not initialize instruction vector DB: {e}", file=sys.stderr)
    
    async def _ensure_sdk_db_ready(self):
        """Ensure the SDK vector database is fully initialized"""
        # Trigger lazy loading by accessing the property  
        _ = self.sdk_integration
        
        # Initialize if not already done
        if hasattr(self.sdk_integration, 'initialize'):
            try:
                await self.sdk_integration.initialize(force_rebuild=False)
            except Exception as e:
                print(f"Warning: Could not initialize SDK vector DB: {e}", file=sys.stderr)
        
    def _register_tools(self):
        """Register all MCP tools - lightweight, no vector DB initialization"""
        self.server.add_tool(
            "search_instructions",
            "Search for PLC instructions by name, category, or description",
            self.search_instructions
        )
        
        self.server.add_tool(
            "get_instruction",
            "Get detailed information about a specific PLC instruction",
            self.get_instruction
        )
        
        self.server.add_tool(
            "list_categories",
            "List all available instruction categories",
            self.list_categories
        )
        
        self.server.add_tool(
            "list_instructions_by_category",
            "List all instructions in a specific category",
            self.list_instructions_by_category
        )
        
        self.server.add_tool(
            "get_instruction_syntax",
            "Get the syntax and parameters for a specific instruction",
            self.get_instruction_syntax
        )
        
        # Add new AI-powered code generation tools
        self.server.add_tool(
            "generate_ladder_logic",
            "Generate ladder logic from natural language specification",
            self.generate_ladder_logic
        )
        
        self.server.add_tool(
            "create_l5x_project",
            "Create complete L5X project file from specification",
            self.create_l5x_project
        )
        
        self.server.add_tool(
            "create_l5x_routine",
            "Create L5X routine export file that can be imported into existing ACD projects",
            self.create_l5x_routine
        )
        
        self.server.add_tool(
            "validate_ladder_logic", 
            "Fast and reliable validation of ladder logic using Studio 5000 documentation",
            self.validate_ladder_logic
        )
        
        if SDK_ENABLED:
            self.server.add_tool("create_acd_project", "Create a Studio 5000 .ACD project using the SDK", self.create_acd_project)
            self.server.add_tool("search_sdk_documentation", "Search Studio 5000 SDK documentation", self.search_sdk_documentation)
            self.server.add_tool("get_sdk_operation_info", "Get details about an SDK operation", self.get_sdk_operation_info)
            self.server.add_tool("list_sdk_categories", "List SDK operation categories", self.list_sdk_categories)
            self.server.add_tool("get_sdk_operations_by_category", "List SDK operations in a category", self.get_sdk_operations_by_category)
            self.server.add_tool("get_logix_project_methods", "Get LogixProject methods", self.get_logix_project_methods)
            self.server.add_tool("suggest_sdk_operations", "Suggest relevant SDK operations", self.suggest_sdk_operations)
            self.server.add_tool("get_sdk_statistics", "Get SDK documentation statistics", self.get_sdk_statistics)
        
        # Add L5X analyzer tools for production-scale L5X files
        self.server.add_tool(
            "index_exported_l5x_files", 
            "Index exported L5X files directly for semantic search",
            self.index_exported_l5x_files
        )
        
        self.server.add_tool(
            "index_acd_project",
            "Index ACD/L5K project for semantic search of routines and components",
            self.index_acd_project
        )

        self.server.add_tool(
            "convert_acd_to_l5x",
            "Generate a v38 L5X from an ACD using the offline vendored parser. Preserves "
            "rung and operand comments and can report semantic parity against a matching Studio export.",
            self.convert_acd_to_l5x
        )
        
        self.server.add_tool(
            "search_l5x_content",
            "Semantic search within indexed L5X content",
            self.search_l5x_content
        )
        
        self.server.add_tool(
            "find_insertion_point",
            "Find optimal location to insert new ladder logic",
            self.find_insertion_point
        )
        
        self.server.add_tool(
            "smart_insert_logic",
            "Directly insert new ladder logic into L5X file at optimal location",
            self.smart_insert_logic
        )
        
        self.server.add_tool(
            "extract_routine_content",
            "Extract specific routine content for analysis",
            self.extract_routine_content
        )
        
        self.server.add_tool(
            "analyze_routine_structure",
            "Analyze structure and complexity of an indexed routine",
            self.analyze_routine_structure
        )
        
        self.server.add_tool(
            "find_related_components",
            "Find components related to a given component",
            self.find_related_components
        )
        
        self.server.add_tool(
            "get_project_overview",
            "Get comprehensive overview of project structure",
            self.get_project_overview
        )
        
        # Add PDF drawings tools
        self.server.add_tool(
            "index_pdf_drawings",
            "Index PDF technical drawings file for semantic search",
            self.index_pdf_drawings
        )
        
        self.server.add_tool(
            "search_drawings",
            "Search technical drawings using natural language",
            self.search_drawings
        )
        
        self.server.add_tool(
            "find_equipment_context",
            "Find all drawings and context related to specific equipment",
            self.find_equipment_context
        )
        
        self.server.add_tool(
            "get_drawing_details",
            "Get detailed information about a specific drawing",
            self.get_drawing_details
        )
        
        self.server.add_tool(
            "get_equipment_connections",
            "Get electrical connections and wiring info for equipment",
            self.get_equipment_connections
        )
        
        # Add tag analyzer tools for Studio 5000 tag CSV files
        self.server.add_tool(
            "index_tag_csv",
            "Index Studio 5000 tag CSV export for semantic search",
            self.index_tag_csv
        )
        
        self.server.add_tool(
            "search_tags",
            "Search through indexed tags using natural language",
            self.search_tags
        )
        
        self.server.add_tool(
            "find_device",
            "Find specific devices by description or function",
            self.find_device
        )
        
        self.server.add_tool(
            "get_module_tags",
            "Get all tags for a specific module (rack/slot)",
            self.get_module_tags
        )
        
        self.server.add_tool(
            "find_i_o_point",
            "Find specific I/O points by address or description",
            self.find_i_o_point
        )
        
        self.server.add_tool(
            "analyze_i_o_usage",
            "Analyze I/O usage and capacity across the system",
            self.analyze_i_o_usage
        )
        
        self.server.add_tool(
            "find_related_tags",
            "Find tags related to a given tag",
            self.find_related_tags
        )
        
        self.server.add_tool(
            "get_device_overview",
            "Get comprehensive overview of devices in the system",
            self.get_device_overview
        )
        
        self.server.add_tool(
            "get_safety_tags",
            "Get all safety-related tags",
            self.get_safety_tags
        )
        
        self.server.add_tool(
            "get_motor_tags",
            "Get all motor control tags",
            self.get_motor_tags
        )
        
        self.server.add_tool(
            "get_sensor_tags",
            "Get all sensor tags",
            self.get_sensor_tags
        )
        
        self.server.add_tool(
            "get_uncommented_tags",
            "COMMENT PIPELINE (pre-check only): scan an L5X/ACD for tag-level items missing comments. "
            "This does NOT cover operands/rung comments and is NOT the way to generate documentation. "
            "To generate logic + tag comments for a program/ACD, start with analyze_comment_graph.",
            self.get_uncommented_tags
        )

        self.server.add_tool(
            "get_tag_reasoning_context",
            "COMMENT PIPELINE step 2 (resolve one escalation): given a single operand/tag that "
            "analyze_comment_graph returned in `assistance_requests`, return its rungs, cross-references, "
            "and neighbouring tag descriptions so you can author an accurate comment FROM THE ACTUAL LOGIC "
            "instead of guessing. Call once per assistance_request you are resolving.",
            self.get_tag_reasoning_context
        )

        self.server.add_tool(
            "generate_comment_deliverables",
            "COMMENT PIPELINE step 3 (final render): turn a COMPLETE decision list into all four Studio 5000 "
            "deliverables in one folder — Comment_Delta.CSV (importable), comment_review_report.html, "
            "decisions.json, and comment_memory.json. Pass EVERY decision: the evidence-backed ones from "
            "analyze_comment_graph PLUS the one you authored for each assistance_request (do not drop any). "
            "Decision dict = {TYPE: 'COMMENT' for an operand / 'Tag' for a tag description, SCOPE: <controller "
            "name, e.g. THAWROOM>, NAME: <full operand path e.g. N101[20].1, or tag name>, "
            "PROPOSED_DESCRIPTION: <text; prefix with 'Candidate: ' when confidence is low>, CONFIDENCE, "
            "STATUS, RATIONALE}. Set edit_acd=True only when you also need an updated .ACD written. "
            "Pass file_path so decisions.json/comment_memory.json are emitted.",
            self.generate_comment_deliverables
        )

        self.server.add_tool(
            "manage_comment_memory",
            "COMMENT PIPELINE (optional): persist decisions + per-routine hashes so re-runs skip unchanged "
            "routines. generate_comment_deliverables already writes comment_memory.json; use this only for "
            "cross-run incremental tracking.",
            self.manage_comment_memory
        )

        self.server.add_tool(
            "generate_program_comments",
            "COMMENT PIPELINE — RECOMMENDED ONE-CALL ENTRY POINT to generate logic/tag comments for an entire "
            "program or ACD. Runs the analysis AND pre-fetches routine-logic reasoning context for every "
            "escalated operand/tag in a single pass, so you get a work packet back: `auto_decisions` "
            "(evidence-backed, ready to pass through) and `to_resolve` (each escalation with its rungs + a "
            "pre-filled `draft_decision` skeleton). Fill each draft_decision's PROPOSED_DESCRIPTION from the "
            "rung_references (prefix 'Candidate: ' when low confidence; items with occurrence_count=0 have no "
            "logic evidence), then call generate_comment_deliverables(decisions=auto_decisions+your_drafts, "
            "output_dir=..., file_path=<acd>). Params: routine_filter (scope to one routine), offset/limit "
            "(paginate to_resolve). Prefer this over calling analyze_comment_graph + get_tag_reasoning_context "
            "separately.",
            self.generate_program_comments
        )

        self.server.add_tool(
            "analyze_comment_graph",
            "COMMENT PIPELINE step 1 (low-level) — used by generate_program_comments; call that instead unless "
            "you need raw analysis. ALWAYS START HERE if generating comments manually for an entire program "
            "or ACD. Builds a typed dependency graph and returns `decisions` (evidence-backed, automatic) AND "
            "`assistance_requests` (operands/tags with no direct evidence that YOU must resolve from routine "
            "logic). RULES: do not hand-author comments without running this first; do not skip or fabricate "
            "assistance_requests; resolve every one from the logic. Then follow the `next_steps` block in the "
            "result — resolve each assistance_request via get_tag_reasoning_context and call "
            "generate_comment_deliverables with the COMBINED decision set. Pass generate_deliverables=True (and "
            "edit_acd=True only if you also need an updated .ACD).",
            self.analyze_comment_graph
        )

        # Ignition SCADA exporter tools (offline; L5X/ACD -> Ignition v8.1+ JSON)
        self.server.add_tool(
            "extract_analog_scaling",
            "Signal-flow-aware analog scaling detector. For each analog point reports the "
            "engineering range and the recommended OPC tag (the .Output for inputs, the .Input "
            "command for outputs), reading real member ranges from the authoritative source and "
            "flagging the raw-hardware fallback when Ignition must convert. Never assumes standard "
            "raw ranges; never silently drops a point.",
            self.extract_analog_scaling
        )
        self.server.add_tool(
            "list_ignition_tag_candidates",
            "Present the full, categorized tag inventory of an L5X/ACD project (category, signal "
            "type, and an operator-facing 'recommended' flag per tag) so you can curate which tags "
            "belong in a SCADA import BEFORE generating. Ask the user when unsure, then pass your "
            "curated selection to generate_ignition_tags as target_tags. Use this first for any "
            "'key process metrics'-style request.",
            self.list_ignition_tag_candidates
        )
        self.server.add_tool(
            "generate_ignition_tags",
            "Generate an Ignition v8.1+ JSON tag export from an L5X/ACD project: program-scope OPC "
            "paths, correct raw->scaled scaling, historian defaults, folder hierarchy, and unicode "
            "escaping. Curated by default (selection='key_process_metrics'); pass target_tags to "
            "import an explicit curated list (see list_ignition_tag_candidates), or selection='all' "
            "to export every addressable tag. Excludes ExternalAccess=None tags and refuses to "
            "overwrite the read-only baseline ignitionTags.json. Requires engineering review.",
            self.generate_ignition_tags
        )
        self.server.add_tool(
            "audit_opc_item_paths",
            "Case-sensitive audit of an Ignition export's opcItemPath references against the L5X "
            "controller tag DB. Reports missing tags, case mismatches (Logix OPC needs exact case), "
            "and ExternalAccess=None references that will not bind.",
            self.audit_opc_item_paths
        )
        self.server.add_tool(
            "suggest_historian_config",
            "Recommend Tag Historian settings (historyEnabled, historyTimeDeadband) by signal type. "
            "Value deadband is returned as advisory output only and is never written into a tag.",
            self.suggest_historian_config
        )
        self.server.add_tool(
            "propose_folder_structures",
            "Propose 2-3 candidate Ignition folder trees (PhysicalSubsystem, EquipmentClass, "
            "AreaLocation) generically from a project's tags, each with a one-line rationale.",
            self.propose_folder_structures
        )
        self.server.add_tool(
            "sanitize_ignition_nodes",
            "Preview Ignition node-name sanitization for a string or list of names (strips illegal "
            "characters that cause 'Error loading node' import failures).",
            self.sanitize_ignition_nodes
        )

        # Performance monitoring tools
        self.server.add_tool(
            "get_cache_performance",
            "Get vector database cache performance statistics",
            self.get_cache_performance
        )

    async def search_instructions(self, query: str, category: Optional[str] = None) -> List[Dict]:
        """Enhanced search for instructions using vector database"""
        try:
            # Ensure vector database is ready
            await self._ensure_instruction_db_ready()
            
            # Use vector database for semantic search
            vector_results = await self.instruction_tools.search_instructions(query, category)
            if vector_results.get('success', False):
                return vector_results.get('results', [])
            else:
                # Fallback to basic search if vector search fails
                import sys
                print(f"Vector search failed, using fallback: {vector_results.get('error', 'Unknown error')}", file=sys.stderr)
                return self._basic_search_instructions(query, category)
        except Exception as e:
            # Fallback to basic search
            import sys
            print(f"Vector search error, using fallback: {e}", file=sys.stderr)
            return self._basic_search_instructions(query, category)
    
    def _basic_search_instructions(self, query: str, category: Optional[str] = None) -> List[Dict]:
        """Fallback basic search for instructions (original implementation)"""
        results = []
        query_lower = query.lower()
        
        for name, instruction in self.instructions.items():
            match_score = 0
            
            # Name match (highest priority)
            if query_lower in instruction.name.lower():
                match_score += 10
            
            # Description match
            if instruction.description and query_lower in instruction.description.lower():
                match_score += 5
            
            # Category filter
            if category and instruction.category.lower() != category.lower():
                continue
            
            if match_score > 0:
                results.append({
                    'name': instruction.name,
                    'category': instruction.category,
                    'description': instruction.description,
                    'languages': instruction.languages,
                    'match_score': match_score,
                    'search_type': 'basic_fallback'
                })
        
        # Sort by match score
        results.sort(key=lambda x: x['match_score'], reverse=True)
        return results[:20]  # Limit to top 20 results
    
    async def get_instruction(self, name: str) -> Optional[Dict]:
        """Get detailed information about a specific instruction using vector database"""
        try:
            # Ensure vector database is ready
            await self._ensure_instruction_db_ready()
            
            # Try vector database first
            vector_result = await self.instruction_tools.get_instruction(name)
            if vector_result.get('success', False):
                return vector_result.get('instruction')
            
            # Fallback to direct lookup
            instruction = self.instructions.get(name.upper())
            if not instruction:
                return None
            
            return {
                'name': instruction.name,
                'category': instruction.category,
                'description': instruction.description,
                'languages': instruction.languages,
                'syntax': instruction.syntax,
                'parameters': instruction.parameters,
                'examples': instruction.examples,
                'file_path': instruction.file_path,
                'search_type': 'direct_fallback'
            }
        except Exception as e:
            # Fallback to direct lookup
            instruction = self.instructions.get(name.upper())
            if not instruction:
                return None
            
            return {
                'name': instruction.name,
                'category': instruction.category,
                'description': instruction.description,
                'languages': instruction.languages,
                'syntax': instruction.syntax,
                'parameters': instruction.parameters,
                'examples': instruction.examples,
                'file_path': instruction.file_path,
                'search_type': 'direct_fallback'
            }
    
    async def list_categories(self) -> List[str]:
        """List all available instruction categories using vector database"""
        try:
            # Ensure vector database is ready
            await self._ensure_instruction_db_ready()
            
            # Try vector database first
            vector_result = await self.instruction_tools.list_categories()
            if vector_result.get('success', False):
                return vector_result.get('categories', [])
            
            # Fallback to direct enumeration
            categories = set()
            for instruction in self.instructions.values():
                if instruction.category:
                    categories.add(instruction.category)
            return sorted(list(categories))
        except Exception as e:
            # Fallback to direct enumeration
            categories = set()
            for instruction in self.instructions.values():
                if instruction.category:
                    categories.add(instruction.category)
            return sorted(list(categories))
    
    async def list_instructions_by_category(self, category: str) -> List[Dict]:
        """List all instructions in a specific category using vector database"""
        try:
            # Ensure vector database is ready
            await self._ensure_instruction_db_ready()
            
            # Try vector database first
            vector_result = await self.instruction_tools.get_instructions_by_category(category)
            if vector_result.get('success', False):
                return vector_result.get('instructions', [])
            
            # Fallback to direct enumeration
            results = []
            category_lower = category.lower()
            
            for instruction in self.instructions.values():
                if instruction.category.lower() == category_lower:
                    results.append({
                        'name': instruction.name,
                        'description': instruction.description,
                        'languages': instruction.languages,
                        'search_type': 'direct_fallback'
                    })
            
            return sorted(results, key=lambda x: x['name'])
        except Exception as e:
            # Fallback to direct enumeration
            results = []
            category_lower = category.lower()
            
            for instruction in self.instructions.values():
                if instruction.category.lower() == category_lower:
                    results.append({
                        'name': instruction.name,
                        'description': instruction.description,
                        'languages': instruction.languages,
                        'search_type': 'direct_fallback'
                    })
            
            return sorted(results, key=lambda x: x['name'])
    
    async def get_instruction_syntax(self, name: str) -> Optional[Dict]:
        """Get syntax and parameter information for an instruction using vector database"""
        try:
            # Ensure vector database is ready
            await self._ensure_instruction_db_ready()
            
            # Try vector database first
            vector_result = await self.instruction_tools.get_instruction_syntax(name)
            if vector_result.get('success', False):
                return vector_result.get('syntax_info')
            
            # Fallback to direct lookup
            instruction = self.instructions.get(name.upper())
            if not instruction:
                return None
            
            return {
                'name': instruction.name,
                'syntax': instruction.syntax,
                'parameters': instruction.parameters,
                'languages': instruction.languages,
                'search_type': 'direct_fallback'
            }
        except Exception as e:
            # Fallback to direct lookup
            instruction = self.instructions.get(name.upper())
            if not instruction:
                return None
            
            return {
                'name': instruction.name,
                'syntax': instruction.syntax,
                'parameters': instruction.parameters,
                'languages': instruction.languages,
                'search_type': 'direct_fallback'
            }
    
    # New AI-powered code generation methods
    async def generate_ladder_logic(self, specification: str) -> Dict[str, Any]:
        """Generate enhanced ladder logic from natural language specification"""
        try:
            # Use the enhanced assistant for better warehouse automation support
            result = await self.enhanced_assistant.generate_ladder_logic(specification)
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': 'Failed to generate ladder logic from specification'
            }
    
    async def create_l5x_project(self, project_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create complete L5X project file using enhanced code generation"""
        try:
            # Use the enhanced assistant for L5X project creation
            result = await self.enhanced_assistant.create_l5x_project(project_spec)
            return result
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': 'Failed to create L5X project'
            }
    
    async def create_l5x_routine(self, routine_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create L5X routine export file that can be imported into existing ACD projects"""
        try:
            from code_generator.l5x_generator import L5XGenerator, Routine, LadderRung
            
            # Extract routine specification
            routine_name = routine_spec.get('name', 'SIMPLE_TEST')
            specification = routine_spec.get('specification', '')
            controller_name = routine_spec.get('controller_name', 'MTN6_MCM06')
            software_revision = routine_spec.get('software_revision', '36.02')
            save_path = routine_spec.get('save_path')
            
            # Generate ladder logic using enhanced assistant
            ladder_result = await self.enhanced_assistant.generate_ladder_logic(specification)
            
            if not ladder_result.get('success', False):
                return {
                    'success': False,
                    'error': ladder_result.get('error', 'Failed to generate ladder logic'),
                    'message': 'Failed to generate ladder logic for routine'
                }
            
            # Parse the generated ladder logic into rungs
            ladder_logic = ladder_result.get('ladder_logic', '')
            ladder_lines = [line.strip() for line in ladder_logic.split('\n') if line.strip()]
            
            # Create rungs from ladder logic
            rungs = []
            rung_number = 0
            current_comment = None
            
            for line in ladder_lines:
                if line.startswith('//'):
                    # This is a comment for the next rung
                    current_comment = line[2:].strip()
                elif line and not line.startswith('//'):
                    # This is ladder logic
                    rung = LadderRung(
                        number=rung_number,
                        logic=line,
                        comment=current_comment
                    )
                    rungs.append(rung)
                    rung_number += 1
                    current_comment = None
            
            # If no rungs were created, create a simple default rung
            if not rungs:
                rungs = [
                    LadderRung(
                        number=0,
                        logic="XIC(Start_Test)XIO(Stop_Test)OTL(Test_Running);",
                        comment="Start/Stop logic"
                    ),
                    LadderRung(
                        number=1,
                        logic="XIC(Test_Running)TON(Test_Timer,5000,0);",
                        comment="Timer logic - 5 second timer"
                    ),
                    LadderRung(
                        number=2,
                        logic="XIC(Test_Timer.EN)OTE(Test_Output);",
                        comment="Output active during timer"
                    ),
                    LadderRung(
                        number=3,
                        logic="XIC(Test_Timer.DN)OTU(Test_Running);",
                        comment="Auto-reset when timer done"
                    )
                ]
            
            # Create the routine
            routine = Routine(
                name=routine_name,
                type="RLL",
                rungs=rungs,
                description=f"Generated routine: {specification[:100]}..."
            )
            
            # Extract tags from the ladder result
            tags = []
            if 'tags' in ladder_result:
                for tag in ladder_result['tags']:
                    tags.append({
                        'name': tag['name'],
                        'data_type': tag['data_type'],
                        'description': tag.get('description', '')
                    })
            else:
                # Default tags for the simple test routine
                tags = [
                    {'name': 'Start_Test', 'data_type': 'BOOL', 'description': 'Start test button'},
                    {'name': 'Stop_Test', 'data_type': 'BOOL', 'description': 'Stop test button'},
                    {'name': 'Test_Running', 'data_type': 'BOOL', 'description': 'Test running status'},
                    {'name': 'Test_Timer', 'data_type': 'TIMER', 'description': '5 second test timer', 'preset_value': 5000},
                    {'name': 'Test_Output', 'data_type': 'BOOL', 'description': 'Test output'}
                ]
            
            # Generate the routine export L5X
            generator = L5XGenerator()
            l5x_content = generator.generate_routine_export(
                routine=routine,
                controller_name=controller_name,
                tags=tags,
                software_revision=software_revision
            )
            
            # Save to file if path provided
            file_saved = False
            if save_path:
                file_saved = generator.save_routine_export(
                    routine=routine,
                    file_path=save_path,
                    controller_name=controller_name,
                    tags=tags,
                    software_revision=software_revision
                )
            
            return {
                'success': True,
                'routine_name': routine_name,
                'controller_name': controller_name,
                'l5x_content': l5x_content,
                'ladder_logic': ladder_logic,
                'tags_created': len(tags),
                'rungs_created': len(rungs),
                'instructions_used': ladder_result.get('instructions_used', []),
                'file_saved': file_saved,
                'save_path': save_path,
                'export_type': 'routine_export'
            }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': 'Failed to create L5X routine export'
            }
    
    async def validate_ladder_logic(self, logic_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Validate ladder logic using enhanced validation with Studio 5000 documentation"""
        try:
            # Use the enhanced assistant for comprehensive validation
            result = await self.enhanced_assistant.validate_ladder_logic(logic_spec)
            return result
            
        except Exception as e:
            return {
                'valid': False,
                'error': str(e),
                'message': 'Failed to validate ladder logic'
            }
    
    async def create_acd_project(self, project_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create real Studio 5000 .ACD project file using enhanced assistant and official SDK"""
        try:
            # Use the enhanced assistant for ACD project creation
            result = await self.enhanced_assistant.create_acd_project(project_spec)
            return result
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': 'Failed to create .ACD project using Studio 5000 SDK'
            }
    
    # New SDK Documentation Search Methods
    async def search_sdk_documentation(self, query: str, limit: Optional[int] = 10) -> Dict[str, Any]:
        """Search Studio 5000 SDK documentation using natural language"""
        try:
            await self._ensure_sdk_db_ready()  # Ensure SDK database is initialized
            result = await self.sdk_tools.search_sdk_documentation(query, limit)
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'query': query,
                'message': 'Failed to search SDK documentation'
            }
    
    async def get_sdk_operation_info(self, name: str, operation_type: Optional[str] = None) -> Dict[str, Any]:
        """Get detailed information about a specific SDK operation"""
        try:
            await self._ensure_sdk_db_ready()  # Ensure SDK database is initialized
            result = await self.sdk_tools.get_sdk_operation_info(name, operation_type)
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'name': name,
                'message': 'Failed to get SDK operation info'
            }
    
    async def list_sdk_categories(self) -> Dict[str, Any]:
        """List all SDK operation categories"""
        try:
            await self._ensure_sdk_db_ready()  # Ensure SDK database is initialized
            result = await self.sdk_tools.list_sdk_categories()
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': 'Failed to list SDK categories'
            }
    
    async def get_sdk_operations_by_category(self, category: str) -> Dict[str, Any]:
        """Get all SDK operations in a specific category"""
        try:
            await self._ensure_sdk_db_ready()  # Ensure SDK database is initialized
            result = await self.sdk_tools.get_sdk_operations_by_category(category)
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'category': category,
                'message': 'Failed to get SDK operations by category'
            }
    
    async def get_logix_project_methods(self, method_category: Optional[str] = None) -> Dict[str, Any]:
        """Get LogixProject methods, optionally filtered by category"""
        try:
            await self._ensure_sdk_db_ready()  # Ensure SDK database is initialized
            result = await self.sdk_tools.get_logix_project_methods(method_category)
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'method_category': method_category,
                'message': 'Failed to get LogixProject methods'
            }
    
    async def suggest_sdk_operations(self, context: str) -> Dict[str, Any]:
        """Suggest relevant SDK operations based on context"""
        try:
            await self._ensure_sdk_db_ready()  # Ensure SDK database is initialized
            result = await self.sdk_tools.suggest_sdk_operations(context)
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'context': context,
                'message': 'Failed to suggest SDK operations'
            }
    
    async def get_sdk_statistics(self) -> Dict[str, Any]:
        """Get SDK documentation statistics and overview"""
        try:
            await self._ensure_sdk_db_ready()  # Ensure SDK database is initialized
            result = await self.sdk_tools.get_sdk_statistics()
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': 'Failed to get SDK statistics'
            }
    
    # L5X Analyzer Tools for Production-Scale L5X Files
    
    async def index_exported_l5x_files(self, l5x_directory: str, force_rebuild: bool = False) -> Dict[str, Any]:
        """Index exported L5X files directly for semantic search"""
        try:
            if not hasattr(self, 'l5x_integration') or self.l5x_integration is None:
                await self._ensure_l5x_tools_initialized()
            
            result = self.l5x_integration.index_exported_l5x_files(l5x_directory, force_rebuild)
            return result
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'message': 'Failed to index exported L5X files'
            }

    async def index_acd_project(self, acd_path: str, routines_to_index: Optional[List[str]] = None,
                               force_rebuild: bool = False) -> Dict[str, Any]:
        """Index ACD/L5K project for semantic search"""
        return await self.l5x_integration.index_acd_project(
            acd_path, routines_to_index, force_rebuild
        )

    async def convert_acd_to_l5x(self, acd_path: str, output_path: Optional[str] = None,
                                 reference_path: Optional[str] = None) -> Dict[str, Any]:
        """Generate a fresh L5X export from an ACD file via the offline vendored parser."""
        from l5x_analyzer.acd_offline_convert import convert_acd_to_l5x as _convert

        source = Path(acd_path)
        resolved_output = output_path or str(source.with_name(f"{source.stem}.Offline.L5X"))
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _convert, acd_path, resolved_output, True, reference_path)
    
    async def search_l5x_content(self, query: str, file_filter: Optional[str] = None,
                               component_type: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """Semantic search within indexed L5X content"""
        return await self.l5x_integration.search_l5x_content(
            query, file_filter, component_type, limit
        )
    
    async def find_insertion_point(self, new_logic_description: str, target_routine: str,
                                 target_file: Optional[str] = None) -> Dict[str, Any]:
        """Find optimal location to insert new ladder logic"""
        return await self.l5x_integration.find_insertion_point(
            new_logic_description, target_routine, target_file
        )
    
    async def smart_insert_logic(self, l5x_file_path: str, routine_name: str, 
                               logic_description: str, program_name: str = "MainProgram",
                               insertion_mode: str = "optimal") -> Dict[str, Any]:
        """Directly insert new ladder logic into L5X file at optimal location"""
        return await self.l5x_integration.smart_insert_logic(
            l5x_file_path, routine_name, logic_description, program_name, insertion_mode
        )
    
    async def extract_routine_content(self, acd_path: str, routine_name: str,
                                    program_name: str = "MainProgram", 
                                    output_format: str = "summary") -> Dict[str, Any]:
        """Extract specific routine content for analysis"""
        return await self.l5x_integration.extract_routine_content(
            acd_path, routine_name, program_name, output_format
        )
    
    async def analyze_routine_structure(self, routine_name: str) -> Dict[str, Any]:
        """Analyze structure and complexity of an indexed routine"""
        return await self.l5x_integration.analyze_routine_structure(routine_name)
    
    async def find_related_components(self, component_name: str, project_filter: Optional[str] = None,
                                    relationship_type: str = "usage") -> Dict[str, Any]:
        """Find components related to a given component"""
        return await self.l5x_integration.find_related_components(
            component_name, project_filter, relationship_type
        )
    
    async def get_project_overview(self, acd_path: str) -> Dict[str, Any]:
        """Get comprehensive overview of project structure"""
        return await self.l5x_integration.get_project_overview(acd_path)
    
    # PDF Drawings Tool Handlers
    async def index_pdf_drawings(self, pdf_file_path: str, force_rebuild: bool = False, 
                               use_vision_ai: bool = False, max_pages: Optional[int] = None) -> Dict[str, Any]:
        """Index PDF technical drawings file for semantic search"""
        return await self.pdf_integration.index_pdf_drawings(
            pdf_file_path, force_rebuild, use_vision_ai, max_pages
        )
    
    async def search_drawings(self, query: str, limit: int = 10, score_threshold: float = 0.3,
                            drawing_type_filter: Optional[str] = None, 
                            equipment_filter: Optional[str] = None) -> Dict[str, Any]:
        """Search technical drawings using natural language"""
        return await self.pdf_integration.search_drawings(
            query, limit, score_threshold, drawing_type_filter, equipment_filter
        )
    
    async def find_equipment_context(self, equipment_tag: str, context_type: Optional[str] = None) -> Dict[str, Any]:
        """Find all drawings and context related to specific equipment"""
        return await self.pdf_integration.find_equipment_context(equipment_tag, context_type)
    
    async def get_drawing_details(self, drawing_number: Optional[str] = None, 
                                page_number: Optional[int] = None) -> Dict[str, Any]:
        """Get detailed information about a specific drawing"""
        return await self.pdf_integration.get_drawing_details(drawing_number, page_number)
    
    async def get_equipment_connections(self, equipment_tag: str) -> Dict[str, Any]:
        """Get electrical connections and wiring info for equipment"""
        return await self.pdf_integration.get_equipment_connections(equipment_tag)
    
    # Tag Analyzer Tool Handlers
    async def index_tag_csv(self, csv_path: str, force_rebuild: bool = False) -> Dict[str, Any]:
        """Index Studio 5000 tag CSV export for semantic search"""
        return await self.tag_integration.index_tag_csv(csv_path, force_rebuild)
    
    async def search_tags(self, query: str, category_filter: str = None, 
                         chunk_type_filter: str = None, limit: int = 20) -> Dict[str, Any]:
        """Search through indexed tags using natural language"""
        return await self.tag_integration.search_tags(query, category_filter, chunk_type_filter, limit)
    
    async def find_device(self, device_description: str, device_type: str = None) -> Dict[str, Any]:
        """Find specific devices by description or function"""
        return await self.tag_integration.find_device(device_description, device_type)
    
    async def get_module_tags(self, rack: int, slot: int) -> Dict[str, Any]:
        """Get all tags for a specific module (rack/slot)"""
        return await self.tag_integration.get_module_tags(rack, slot)
    
    async def find_i_o_point(self, address_pattern: str = None, description: str = None) -> Dict[str, Any]:
        """Find specific I/O points by address or description"""
        return await self.tag_integration.find_i_o_point(address_pattern, description)
    
    async def analyze_i_o_usage(self) -> Dict[str, Any]:
        """Analyze I/O usage and capacity across the system"""
        return await self.tag_integration.analyze_i_o_usage()
    
    async def find_related_tags(self, tag_name: str, relationship_type: str = "all") -> Dict[str, Any]:
        """Find tags related to a given tag"""
        return await self.tag_integration.find_related_tags(tag_name, relationship_type)
    
    async def get_device_overview(self, category_filter: str = None) -> Dict[str, Any]:
        """Get comprehensive overview of devices in the system"""
        return await self.tag_integration.get_device_overview(category_filter)
    
    async def get_safety_tags(self) -> Dict[str, Any]:
        """Get all safety-related tags"""
        return await self.tag_integration.get_safety_tags()
    
    async def get_motor_tags(self) -> Dict[str, Any]:
        """Get all motor control tags"""
        return await self.tag_integration.get_motor_tags()
    
    async def get_sensor_tags(self) -> Dict[str, Any]:
        """Get all sensor tags"""
        return await self.tag_integration.get_sensor_tags()

    async def get_uncommented_tags(self, file_path: str, scope_filter: Optional[str] = None) -> Dict[str, Any]:
        """Scan L5X or ACD for tags missing comments or descriptions"""
        return await self.tag_integration.get_uncommented_tags(file_path, scope_filter)

    async def get_tag_reasoning_context(self, tag_name: str, file_path: str) -> Dict[str, Any]:
        """Extract rich ladder logic context, rungs, and adjacent tag descriptions for tag reasoning"""
        return await self.tag_integration.get_tag_reasoning_context(tag_name, file_path)

    async def generate_comment_deliverables(
        self,
        decisions: Optional[List[Dict[str, Any]]] = None,
        output_dir: Optional[str] = None,
        project_name: Optional[str] = None,
        file_path: Optional[str] = None,
        edit_acd: bool = False,
        target_acd: Optional[str] = None,
        decisions_path: Optional[str] = None,
        work_packet_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate Studio 5000 importable Comment_Delta.CSV, interactive comment_review_report.html,
        decisions.json, comment_memory.json (and, when edit_acd is True, an updated .ACD project deliverable).

        When project_name is omitted it is derived from the target ACD/L5X artifact."""
        return await self.tag_integration.generate_comment_deliverables(
            decisions=decisions,
            output_dir=output_dir,
            project_name=project_name,
            file_path=file_path,
            edit_acd=edit_acd,
            target_acd=target_acd,
            decisions_path=decisions_path,
            work_packet_path=work_packet_path,
        )

    async def manage_comment_memory(
        self, file_path: str, memory_file_path: str, decisions_to_save: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Track granular routine/tag hashes to skip unchanged routines and incrementally save decisions"""
        return await self.tag_integration.manage_comment_memory(file_path, memory_file_path, decisions_to_save)

    async def generate_program_comments(
        self,
        acd_path: str,
        routine_filter: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """One-call orchestrator: analyze + pre-fetch reasoning context for every escalation."""
        return await self.tag_integration.generate_program_comments(
            acd_path, routine_filter=routine_filter, offset=offset, limit=limit, config=config,
        )

    async def analyze_comment_graph(
        self,
        file_path: str,
        reference_path: Optional[str] = None,
        generate_deliverables: bool = False,
        output_dir: Optional[str] = None,
        memory_file_path: Optional[str] = None,
        user_seeds: Optional[List[Dict[str, Any]]] = None,
        config: Optional[Dict[str, Any]] = None,
        edit_acd: bool = False,
        target_acd: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Iterative PLC comment analysis over a typed dependency graph.
        When edit_acd is True, an updated .ACD project deliverable is written."""
        return await self.tag_integration.analyze_comment_graph(
            file_path, reference_path, generate_deliverables,
            output_dir, memory_file_path, user_seeds, config,
            edit_acd=edit_acd, target_acd=target_acd,
        )

    # -- Ignition SCADA exporter handlers ---------------------------------
    async def extract_analog_scaling(self, l5x_file_path: str,
                                     target_tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Detect analog scaling per point (signal-flow aware) from an L5X/ACD project."""
        return await self.ignition_integration.extract_analog_scaling(l5x_file_path, target_tags)

    async def list_ignition_tag_candidates(self, l5x_file_path: str) -> Dict[str, Any]:
        """Present the categorized tag inventory for agent-driven curation."""
        return await self.ignition_integration.list_ignition_tag_candidates(l5x_file_path)

    async def generate_ignition_tags(self, l5x_file_path: str, device_name: str,
                                     output_file_path: str,
                                     folder_hierarchy_model: str = "PhysicalSubsystem",
                                     enable_history_defaults: bool = True,
                                     target_tags: Optional[List[str]] = None,
                                     selection: str = "key_process_metrics") -> Dict[str, Any]:
        """Generate an Ignition v8.1+ JSON tag export. Requires engineering review before use."""
        return await self.ignition_integration.generate_ignition_tags(
            l5x_file_path, device_name, output_file_path,
            folder_hierarchy_model=folder_hierarchy_model,
            enable_history_defaults=enable_history_defaults,
            target_tags=target_tags, selection=selection,
        )

    async def audit_opc_item_paths(self, ignition_json_path: str,
                                   l5x_file_path: str) -> Dict[str, Any]:
        """Case-sensitive audit of OPC item paths vs the L5X controller tag DB."""
        return await self.ignition_integration.audit_opc_item_paths(ignition_json_path, l5x_file_path)

    async def suggest_historian_config(self, signal_type: Optional[str] = None,
                                       tag_name: Optional[str] = None,
                                       description: Optional[str] = None,
                                       eng_low: Optional[float] = None,
                                       eng_high: Optional[float] = None) -> Dict[str, Any]:
        """Recommend historian settings by signal type (value deadband is advisory only)."""
        return await self.ignition_integration.suggest_historian_config(
            signal_type=signal_type, tag_name=tag_name, description=description,
            eng_low=eng_low, eng_high=eng_high,
        )

    async def propose_folder_structures(self, l5x_file_path: str,
                                        max_options: int = 3) -> Dict[str, Any]:
        """Propose candidate Ignition folder trees for a project."""
        return await self.ignition_integration.propose_folder_structures(l5x_file_path, max_options)

    async def sanitize_ignition_nodes(self, names) -> Dict[str, Any]:
        """Preview Ignition name sanitization for a string or list of names."""
        return await self.ignition_integration.sanitize_ignition_nodes(names)

    async def get_cache_performance(self) -> Dict[str, Any]:
        """Get vector database cache performance statistics"""
        try:
            stats = shared_cache_manager.get_cache_statistics()
            
            # Add some additional system info
            stats['system_info'] = {
                'instruction_count': len(self.instructions),
                'loaded_systems': []
            }
            
            # Check which systems are loaded
            if self._sdk_integration is not None:
                stats['system_info']['loaded_systems'].append('SDK Documentation')
            if self._instruction_integration is not None:
                stats['system_info']['loaded_systems'].append('Instruction Documentation') 
            if self._l5x_integration is not None:
                stats['system_info']['loaded_systems'].append('L5X Analyzer')
            if self._pdf_integration is not None:
                stats['system_info']['loaded_systems'].append('PDF Drawings')
            if self._tag_integration is not None:
                stats['system_info']['loaded_systems'].append('Tag Analyzer')
            
            return {
                'success': True,
                'cache_statistics': stats,
                'performance_tips': [
                    'Cache hit rates above 80% indicate good performance',
                    'Vector databases load automatically when first accessed',
                    'Shared model reduces memory usage across all vector databases',
                    'Cache files are valid for 30 days by default'
                ]
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f"Failed to get cache statistics: {str(e)}"
            }

# JSON-RPC 2.0 MCP Protocol Implementation
async def handle_mcp_request(server: Studio5000MCPServer, request: Dict) -> Optional[Dict]:
    """Handle an MCP request"""
    method = request.get('method')
    params = request.get('params', {})
    request_id = request.get('id')
    
    # Handle notifications (requests without ID) by returning None
    is_notification = 'id' not in request
    
    # Initialize response with JSON-RPC 2.0 format
    response = {
        "jsonrpc": "2.0"
    }
    
    # Only include ID in response if this is not a notification
    if not is_notification:
        response["id"] = request_id
    
    if method == 'initialize':
        response["result"] = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "studio5000-ai-assistant",
                "version": "2.0.0"
            }
        }
        return response
    
    elif method == 'tools/list':
        tools = []
        for name, tool in server.server.tools.items():
            # Build properties and required fields based on tool name
            properties = {}
            required = []
            
            if name == 'search_instructions':
                properties = {
                    'query': {'type': 'string', 'description': 'Search query'},
                    'category': {'type': 'string', 'description': 'Optional category filter'}
                }
                required = ['query']
            elif name in ['get_instruction', 'get_instruction_syntax']:
                properties = {
                    'name': {'type': 'string', 'description': 'Instruction name'}
                }
                required = ['name']
            elif name == 'list_instructions_by_category':
                properties = {
                    'category': {'type': 'string', 'description': 'Category name'}
                }
                required = ['category']
            elif name == 'generate_ladder_logic':
                properties = {
                    'specification': {'type': 'string', 'description': 'Natural language specification for PLC logic'}
                }
                required = ['specification']
            elif name == 'create_l5x_project':
                properties = {
                    'project_spec': {
                        'type': 'object',
                        'description': 'Project specification',
                        'properties': {
                            'name': {'type': 'string', 'description': 'Project name'},
                            'controller_type': {'type': 'string', 'description': 'Controller type (e.g., 1756-L83E)'},
                            'specification': {'type': 'string', 'description': 'Natural language specification'},
                            'save_path': {'type': 'string', 'description': 'Optional file path to save L5X file'}
                        }
                    }
                }
                required = ['project_spec']
            elif name == 'create_l5x_routine':
                properties = {
                    'routine_spec': {
                        'type': 'object',
                        'description': 'Routine specification for export',
                        'properties': {
                            'name': {'type': 'string', 'description': 'Routine name'},
                            'controller_name': {'type': 'string', 'description': 'Existing controller name (e.g., MTN6_MCM06)'},
                            'specification': {'type': 'string', 'description': 'Natural language specification for routine logic'},
                            'software_revision': {'type': 'string', 'description': 'Studio 5000 software revision (default: 36.02)'},
                            'save_path': {'type': 'string', 'description': 'File path to save routine L5X export'}
                        }
                    }
                }
                required = ['routine_spec']
            elif name == 'validate_ladder_logic':
                properties = {
                    'logic_spec': {
                        'type': 'object',
                        'description': 'Ladder logic specification to validate using fast, reliable validation',
                        'properties': {
                            'ladder_logic': {'type': 'string', 'description': 'Ladder logic code to validate'},
                            'instructions_used': {'type': 'array', 'description': 'List of instructions used (optional)'},
                            'controller_type': {'type': 'string', 'description': 'Controller type for validation (optional, default: 1756-L83E)'}
                        }
                    }
                }
                required = ['logic_spec']
            elif name == 'create_acd_project':
                properties = {
                    'project_spec': {
                        'type': 'object',
                        'description': 'ACD project specification',
                        'properties': {
                            'name': {'type': 'string', 'description': 'Project name'},
                            'controller_type': {'type': 'string', 'description': 'Controller type (e.g., 1756-L83E)'},
                            'major_revision': {'type': 'integer', 'description': 'Studio 5000 major revision (default 36)'},
                            'save_path': {'type': 'string', 'description': 'File path to save .ACD file'}
                        }
                    }
                }
                required = ['project_spec']
            elif name == 'search_sdk_documentation':
                properties = {
                    'query': {'type': 'string', 'description': 'Natural language query to search SDK documentation'},
                    'limit': {'type': 'integer', 'description': 'Maximum number of results to return (default: 10)'}
                }
                required = ['query']
            elif name == 'get_sdk_operation_info':
                properties = {
                    'name': {'type': 'string', 'description': 'Name of the SDK operation to get details for'},
                    'operation_type': {'type': 'string', 'description': 'Optional operation type filter (method, class, enum, example)'}
                }
                required = ['name']
            elif name == 'list_sdk_categories':
                properties = {}
                required = []
            elif name == 'get_sdk_operations_by_category':
                properties = {
                    'category': {'type': 'string', 'description': 'SDK operation category name'}
                }
                required = ['category']
            elif name == 'get_logix_project_methods':
                properties = {
                    'method_category': {'type': 'string', 'description': 'Optional category to filter LogixProject methods by'}
                }
                required = []
            elif name == 'suggest_sdk_operations':
                properties = {
                    'context': {'type': 'string', 'description': 'Context or description of what you want to accomplish'}
                }
                required = ['context']
            elif name == 'get_sdk_statistics':
                properties = {}
                required = []
            # L5X Analyzer Tools  
            elif name == 'index_exported_l5x_files':
                properties = {
                    'l5x_directory': {'type': 'string', 'description': 'Directory containing exported L5X files'},
                    'force_rebuild': {'type': 'boolean', 'description': 'Force rebuild even if cached (default: false)'}
                }
                required = ['l5x_directory']
            elif name == 'index_acd_project':
                properties = {
                    'acd_path': {'type': 'string', 'description': 'Path to ACD or L5K file to index'},
                    'routines_to_index': {'type': 'array', 'description': 'Optional list of specific routines to index (null for all)'},
                    'force_rebuild': {'type': 'boolean', 'description': 'Force rebuild even if cached (default: false)'}
                }
                required = ['acd_path']
            elif name == 'convert_acd_to_l5x':
                properties = {
                    'acd_path': {'type': 'string', 'description': 'Path to the ACD file to convert'},
                    'output_path': {'type': 'string', 'description': 'Optional output path (default: <name>.Offline.L5X to preserve Studio exports)'},
                    'reference_path': {'type': 'string', 'description': 'Optional matching Studio-exported L5X for semantic parity reporting'}
                }
                required = ['acd_path']
            elif name == 'search_l5x_content':
                properties = {
                    'query': {'type': 'string', 'description': 'Natural language search query'},
                    'file_filter': {'type': 'string', 'description': 'Optional filter by project file name'},
                    'component_type': {'type': 'string', 'description': 'Optional filter by component type (routine, rung, udt, etc.)'},
                    'limit': {'type': 'integer', 'description': 'Maximum results to return (default: 20)'}
                }
                required = ['query']
            elif name == 'find_insertion_point':
                properties = {
                    'new_logic_description': {'type': 'string', 'description': 'Description of logic to insert'},
                    'target_routine': {'type': 'string', 'description': 'Target routine name'},
                    'target_file': {'type': 'string', 'description': 'Optional target file filter'}
                }
                required = ['new_logic_description', 'target_routine']
            elif name == 'smart_insert_logic':
                properties = {
                    'l5x_file_path': {'type': 'string', 'description': 'Path to L5X file to modify'},
                    'routine_name': {'type': 'string', 'description': 'Target routine name'},
                    'logic_description': {'type': 'string', 'description': 'Natural language description of logic to generate and insert'},
                    'program_name': {'type': 'string', 'description': 'Parent program name (default: MainProgram)'},
                    'insertion_mode': {'type': 'string', 'description': 'Insertion mode: optimal or end (default: optimal)'}
                }
                required = ['l5x_file_path', 'routine_name', 'logic_description']
            elif name == 'extract_routine_content':
                properties = {
                    'acd_path': {'type': 'string', 'description': 'Path to ACD/L5K file'},
                    'routine_name': {'type': 'string', 'description': 'Routine to extract'},
                    'program_name': {'type': 'string', 'description': 'Parent program name (default: MainProgram)'},
                    'output_format': {'type': 'string', 'description': 'Output format: summary, full, or rungs_only (default: summary)'}
                }
                required = ['acd_path', 'routine_name']
            elif name == 'analyze_routine_structure':
                properties = {
                    'routine_name': {'type': 'string', 'description': 'Name of routine to analyze'}
                }
                required = ['routine_name']
            elif name == 'find_related_components':
                properties = {
                    'component_name': {'type': 'string', 'description': 'Name of component to find relationships for'},
                    'project_filter': {'type': 'string', 'description': 'Optional project file filter'},
                    'relationship_type': {'type': 'string', 'description': 'Type of relationship: usage, dependency, or similar (default: usage)'}
                }
                required = ['component_name']
            elif name == 'get_project_overview':
                properties = {
                    'acd_path': {'type': 'string', 'description': 'Path to ACD/L5K file'}
                }
                required = ['acd_path']
            
            # PDF Drawings Tool Parameters
            elif name == 'index_pdf_drawings':
                properties = {
                    'pdf_file_path': {'type': 'string', 'description': 'Path to PDF file containing technical drawings'},
                    'force_rebuild': {'type': 'boolean', 'description': 'Force re-indexing even if cached (default: false)'},
                    'use_vision_ai': {'type': 'boolean', 'description': 'Enable advanced vision AI analysis (default: false)'},
                    'max_pages': {'type': 'integer', 'description': 'Limit processing to first N pages for testing (optional)'}
                }
                required = ['pdf_file_path']
            elif name == 'search_drawings':
                properties = {
                    'query': {'type': 'string', 'description': 'Natural language search query'},
                    'limit': {'type': 'integer', 'description': 'Maximum number of results (default: 10)'},
                    'score_threshold': {'type': 'number', 'description': 'Minimum relevance score 0.0-1.0 (default: 0.3)'},
                    'drawing_type_filter': {'type': 'string', 'description': 'Filter by type: electrical, pid, layout, control_logic, etc.'},
                    'equipment_filter': {'type': 'string', 'description': 'Filter by equipment tag'}
                }
                required = ['query']
            elif name == 'find_equipment_context':
                properties = {
                    'equipment_tag': {'type': 'string', 'description': 'Equipment identifier (e.g., MCM01, PDP01, M001)'},
                    'context_type': {'type': 'string', 'description': 'Context type: electrical, process, safety, control (optional)'}
                }
                required = ['equipment_tag']
            elif name == 'get_drawing_details':
                properties = {
                    'drawing_number': {'type': 'string', 'description': 'Drawing reference number (optional)'},
                    'page_number': {'type': 'integer', 'description': 'Page number to retrieve (optional)'}
                }
                required = []  # At least one parameter required, but handled in logic
            elif name == 'get_equipment_connections':
                properties = {
                    'equipment_tag': {'type': 'string', 'description': 'Equipment identifier to find connections for'}
                }
                required = ['equipment_tag']
            
            # Tag Analyzer Tool Parameters
            elif name == 'index_tag_csv':
                properties = {
                    'csv_path': {'type': 'string', 'description': 'Path to Studio 5000 tag CSV export file'},
                    'force_rebuild': {'type': 'boolean', 'description': 'Force rebuild even if cached (default: false)'}
                }
                required = ['csv_path']
            elif name == 'search_tags':
                properties = {
                    'query': {'type': 'string', 'description': 'Natural language search query'},
                    'category_filter': {'type': 'string', 'description': 'Filter by device category (VFD, Safety, DI, DO, etc.)'},
                    'chunk_type_filter': {'type': 'string', 'description': 'Filter by chunk type (safety_tag, motor_tag, sensor_tag, etc.)'},
                    'limit': {'type': 'integer', 'description': 'Maximum results to return (default: 20)'}
                }
                required = ['query']
            elif name == 'find_device':
                properties = {
                    'device_description': {'type': 'string', 'description': 'Description of device to find'},
                    'device_type': {'type': 'string', 'description': 'Optional device type filter'}
                }
                required = ['device_description']
            elif name == 'get_module_tags':
                properties = {
                    'rack': {'type': 'integer', 'description': 'Rack number'},
                    'slot': {'type': 'integer', 'description': 'Slot number'}
                }
                required = ['rack', 'slot']
            elif name == 'find_i_o_point':
                properties = {
                    'address_pattern': {'type': 'string', 'description': 'I/O address pattern to search for (optional)'},
                    'description': {'type': 'string', 'description': 'Description to search for (optional)'}
                }
                required = []  # At least one parameter required, handled in logic
            elif name == 'analyze_i_o_usage':
                properties = {}
                required = []
            elif name == 'find_related_tags':
                properties = {
                    'tag_name': {'type': 'string', 'description': 'Tag name to find relationships for'},
                    'relationship_type': {'type': 'string', 'description': 'Type of relationship (all, functional, physical)'}
                }
                required = ['tag_name']
            elif name == 'get_device_overview':
                properties = {
                    'category_filter': {'type': 'string', 'description': 'Optional category filter'}
                }
                required = []
            elif name in ['get_safety_tags', 'get_motor_tags', 'get_sensor_tags']:
                properties = {}
                required = []
            elif name == 'get_uncommented_tags':
                properties = {
                    'file_path': {'type': 'string', 'description': 'Path to ACD or L5X file'},
                    'scope_filter': {'type': 'string', 'description': 'Optional scope filter (Controller or Program name)'}
                }
                required = ['file_path']
            elif name == 'get_tag_reasoning_context':
                properties = {
                    'tag_name': {'type': 'string', 'description': 'Tag name to extract reasoning context for'},
                    'file_path': {'type': 'string', 'description': 'Path to ACD or L5X file'}
                }
                required = ['tag_name', 'file_path']
            elif name == 'generate_program_comments':
                properties = {
                    'acd_path': {'type': 'string', 'description': 'Path to ACD or L5X project file'},
                    'routine_filter': {'type': 'string', 'description': 'Optional routine name filter'},
                    'offset': {'type': 'integer', 'description': 'Pagination offset for to_resolve items (default: 0)'},
                    'limit': {'type': 'integer', 'description': 'Pagination limit for to_resolve items (default: 50)'},
                    'config': {'type': 'object', 'description': 'Optional AnalysisConfig overrides'}
                }
                required = ['acd_path']
            elif name == 'generate_comment_deliverables':
                properties = {
                    'decisions': {'type': 'array', 'description': 'List of proposed comment decision dicts (inline)'},
                    'decisions_path': {'type': 'string', 'description': 'Path to JSON file containing decisions list'},
                    'work_packet_path': {'type': 'string', 'description': 'Path to work_packet.json to auto-merge and render'},
                    'output_dir': {'type': 'string', 'description': 'Output directory for deliverables (defaults to folder alongside target file)'},
                    'project_name': {'type': 'string', 'description': 'Project name for report header'},
                    'file_path': {'type': 'string', 'description': 'Path to reference target ACD or L5X file'},
                    'edit_acd': {'type': 'boolean', 'description': 'Directly edit comments/rungs in the ACD file and output an updated .ACD deliverable'},
                    'target_acd': {'type': 'string', 'description': 'Explicit path to target ACD file to edit'}
                }
                required = []
            elif name == 'manage_comment_memory':
                properties = {
                    'file_path': {'type': 'string', 'description': 'Path to ACD or L5X file'},
                    'memory_file_path': {'type': 'string', 'description': 'Path to memory JSON file'},
                    'decisions_to_save': {'type': 'array', 'description': 'Optional decision dicts to save'}
                }
                required = ['file_path', 'memory_file_path']
            elif name == 'analyze_comment_graph':
                properties = {
                    'file_path': {'type': 'string', 'description': 'Path to native L5X (authoritative) or ACD (converted offline) file'},
                    'reference_path': {'type': 'string', 'description': 'Optional reference L5X for ACD conversion validation'},
                    'generate_deliverables': {'type': 'boolean', 'description': 'Render Comment_Delta.CSV / HTML from the converged state'},
                    'output_dir': {'type': 'string', 'description': 'Output directory for deliverables (defaults to folder alongside target file)'},
                    'memory_file_path': {'type': 'string', 'description': 'Optional memory JSON path; record is extended with graph_digest and source_artifact_hash'},
                    'user_seeds': {'type': 'array', 'description': 'Optional user decision seeds (UPPERCASE NAME/PROPOSED_DESCRIPTION dicts), tier-2 precedence'},
                    'config': {'type': 'object', 'description': 'Optional AnalysisConfig overrides (max_passes, max_component_passes, max_workers, enable_instruction_doc, enable_vector_retrieval)'},
                    'edit_acd': {'type': 'boolean', 'description': 'Directly edit comments/rungs in the ACD file and output an updated .ACD deliverable'},
                    'target_acd': {'type': 'string', 'description': 'Explicit path to target ACD file to edit'}
                }
                required = ['file_path']
            elif name == 'extract_analog_scaling':
                properties = {
                    'l5x_file_path': {'type': 'string', 'description': 'Path to L5X or ACD project file'},
                    'target_tags': {'type': 'array', 'description': 'Optional list of tag names to restrict the report to'}
                }
                required = ['l5x_file_path']
            elif name == 'list_ignition_tag_candidates':
                properties = {
                    'l5x_file_path': {'type': 'string', 'description': 'Path to L5X or ACD project file'}
                }
                required = ['l5x_file_path']
            elif name == 'generate_ignition_tags':
                properties = {
                    'l5x_file_path': {'type': 'string', 'description': 'Path to source L5X or ACD project file'},
                    'device_name': {'type': 'string', 'description': 'OPC UA device connection name (used in opcItemPath and as the root folder)'},
                    'output_file_path': {'type': 'string', 'description': 'Destination JSON path (must NOT be ignitionTags.json, the read-only baseline)'},
                    'folder_hierarchy_model': {'type': 'string', 'description': "Folder tree model: 'PhysicalSubsystem', 'EquipmentClass', or 'AreaLocation' (default: PhysicalSubsystem)"},
                    'enable_history_defaults': {'type': 'boolean', 'description': 'Apply historian defaults by signal type (default: true). Never writes value deadbands.'},
                    'target_tags': {'type': 'array', 'description': 'Curated list of PLC tag names to import (your selection from list_ignition_tag_candidates). Overrides selection.'},
                    'selection': {'type': 'string', 'description': "When target_tags is omitted: 'key_process_metrics' (curated default) or 'all' (every addressable tag)."}
                }
                required = ['l5x_file_path', 'device_name', 'output_file_path']
            elif name == 'audit_opc_item_paths':
                properties = {
                    'ignition_json_path': {'type': 'string', 'description': 'Path to the Ignition JSON export to audit'},
                    'l5x_file_path': {'type': 'string', 'description': 'Path to the L5X or ACD project file to audit against'}
                }
                required = ['ignition_json_path', 'l5x_file_path']
            elif name == 'suggest_historian_config':
                properties = {
                    'signal_type': {'type': 'string', 'description': "Optional explicit signal type (level, pressure, temperature, flow, speed, energy, alarm, status, static)"},
                    'tag_name': {'type': 'string', 'description': 'Optional tag name used to classify the signal when signal_type is omitted'},
                    'description': {'type': 'string', 'description': 'Optional tag description used to classify the signal'},
                    'eng_low': {'type': 'number', 'description': 'Optional engineering-range low, used to compute an advisory value deadband'},
                    'eng_high': {'type': 'number', 'description': 'Optional engineering-range high, used to compute an advisory value deadband'}
                }
                required = []
            elif name == 'propose_folder_structures':
                properties = {
                    'l5x_file_path': {'type': 'string', 'description': 'Path to L5X or ACD project file'},
                    'max_options': {'type': 'integer', 'description': 'Maximum number of candidate folder trees to return (default: 3)'}
                }
                required = ['l5x_file_path']
            elif name == 'sanitize_ignition_nodes':
                properties = {
                    'names': {'description': 'A single name (string) or a list of names to sanitize for Ignition'}
                }
                required = ['names']

            tools.append({
                'name': name,
                'description': tool['description'],
                'inputSchema': {
                    'type': 'object',
                    'properties': properties,
                    'required': required
                }
            })
        
        response["result"] = {'tools': tools}
        return response
    
    elif method == 'tools/call':
        tool_name = params.get('name')
        arguments = params.get('arguments', {})
        
        if tool_name in server.server.tools:
            handler = server.server.tools[tool_name]['handler']
            try:
                result = await handler(**arguments)
                response["result"] = {
                    'content': [
                        {
                            'type': 'text',
                            'text': json.dumps(result, indent=2)
                        }
                    ]
                }
                return response
            except Exception as e:
                if is_notification:
                    return None
                response["error"] = {
                    'code': -32603,
                    'message': f"Internal error: {str(e)}"
                }
                return response
        else:
            if is_notification:
                return None
            response["error"] = {
                'code': -32601,
                'message': f"Unknown tool: {tool_name}"
            }
            return response
    
    else:
        # Don't send error responses for notifications
        if is_notification:
            return None
            
        response["error"] = {
            'code': -32601,
            'message': f"Unknown method: {method}"
        }
        return response

async def main():
    """Main server entry point"""
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description='Studio 5000 AI-Powered PLC Programming Assistant MCP Server')
    
    # Get default documentation path from environment variable or use fallback
    default_doc_path = os.environ.get(
        'STUDIO5000_DOC_PATH', 
        r'C:\Program Files (x86)\Rockwell Software\Studio 5000\Logix Designer\ENU\v36\Bin\Help\ENU\rs5000'
    )
    
    parser.add_argument('--doc-root', 
                       default=default_doc_path,
                       help='Path to Studio 5000 documentation root directory (can also set STUDIO5000_DOC_PATH env var)')
    parser.add_argument('--test', 
                       action='store_true',
                       help='Run in test mode with sample queries')
    
    args = parser.parse_args()
    
    # Initialize the server
    try:
        mcp_server = Studio5000MCPServer(args.doc_root)
    except Exception as e:
        print(f"Error initializing server: {e}", file=sys.stderr)
        return 1
    
    if args.test:
        # Test mode - run some sample queries
        print("\n=== Testing Studio 5000 MCP Server ===\n")
        
        # Test search
        print("1. Searching for 'timer' instructions:")
        results = await mcp_server.search_instructions("timer")
        for result in results[:5]:
            print(f"  - {result['name']}: {result['description']}")
        
        print("\n2. Getting details for ALMD instruction:")
        almd_info = await mcp_server.get_instruction("ALMD")
        if almd_info:
            print(f"  Name: {almd_info['name']}")
            print(f"  Category: {almd_info['category']}")
            print(f"  Languages: {', '.join(almd_info['languages'])}")
            print(f"  Description: {almd_info['description'][:100]}...")
        
        print("\n3. Listing categories:")
        categories = await mcp_server.list_categories()
        for cat in categories[:10]:
            print(f"  - {cat}")
        
        print(f"\n4. Testing AI code generation:")
        test_spec = "Start the motor when the start button is pressed and stop it when the stop button is pressed"
        result = await mcp_server.generate_ladder_logic(test_spec)
        if result['success']:
            print(f"  Generated logic: {result['ladder_logic']}")
            print(f"  Tags created: {len(result['tags'])}")
            print(f"  Instructions used: {', '.join(result['instructions_used'])}")
        else:
            print(f"  Error: {result.get('error', 'Unknown error')}")
        
        print(f"\n5. Testing L5X project creation:")
        project_spec = {
            'name': 'TestMotorControl',
            'specification': test_spec
        }
        l5x_result = await mcp_server.create_l5x_project(project_spec)
        if l5x_result.get('success'):
            print(f"  L5X Project Creation Success!")
            # Print actual keys to see the structure
            print(f"  Available keys: {list(l5x_result.keys())}")
            if 'project_info' in l5x_result:
                info = l5x_result['project_info']
                print(f"  Project: {info.get('name', 'N/A')}")
                print(f"  Controller: {info.get('controller', 'N/A')}")
                print(f"  Programs: {info.get('programs', 'N/A')}")
                print(f"  Tags: {info.get('tags', 'N/A')}")
            elif 'project_name' in l5x_result:
                print(f"  Project: {l5x_result['project_name']}")
            elif 'name' in l5x_result:
                print(f"  Project: {l5x_result['name']}")
        else:
            print(f"  Error: {l5x_result.get('error', 'Unknown error')}")

        print(f"\n6. Testing iterative comment graph analysis (analyze_comment_graph):")
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        native_fixture = os.path.join(repo_root, 'tests', 'acd', 'ModernTHAWROOM021722.L5X')
        if os.path.exists(native_fixture):
            cg_result = await mcp_server.analyze_comment_graph(native_fixture)
            if cg_result.get('success'):
                print(f"  Convergence: {cg_result.get('convergence_status')}")
                print(f"  Proposed decisions: {len(cg_result.get('decisions', []))}")
                print(f"  Passes: {len(cg_result.get('pass_history', []))}")
                print(f"  Warnings: {len(cg_result.get('warnings', []))}, "
                      f"contradictions: {len(cg_result.get('contradictions', []))}, "
                      f"assistance: {len(cg_result.get('assistance_requests', []))}")
            else:
                print(f"  Error: {cg_result.get('error', 'Unknown error')}")
        else:
            print(f"  Skipped (native fixture not found at {native_fixture})")

        print(f"\n🎉 AI-Powered Studio 5000 Assistant initialized successfully!")
        print(f"📊 Features ready:")
        print(f"  • {len(mcp_server.instructions)} Studio 5000 instructions indexed")
        print(f"  • AI-powered natural language to ladder logic conversion")
        print(f"  • L5X project file generation")
        print(f"  • Instruction validation using official documentation")
        return 0
    
    else:
        # Real MCP server mode - JSON-RPC 2.0 via stdin/stdout
        print("Studio 5000 MCP Server starting...", file=sys.stderr)
        print("Ready to handle MCP requests via stdin/stdout", file=sys.stderr)
        
        # JSON-RPC 2.0 stdin/stdout protocol handler
        while True:
            try:
                line = input()
                if not line:
                    break
                
                request = json.loads(line)
                response = await handle_mcp_request(mcp_server, request)
                
                # Only print response if it's not None (notifications return None)
                if response is not None:
                    print(json.dumps(response), flush=True)
                
            except EOFError:
                break
            except json.JSONDecodeError as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                }
                print(json.dumps(error_response), flush=True)
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0", 
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}"
                    }
                }
                print(json.dumps(error_response), flush=True)

if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
