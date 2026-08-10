#!/usr/bin/env python3
"""
Tag MCP Integration

Integrates the Tag Vector Database with the MCP server, providing tools for semantic search
and analysis of Studio 5000 tag CSV exports.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from enum import Enum

from .tag_vector_db import TagVectorDatabase, TagSearchResult
from .csv_tag_parser import CSVTagParser
from .tag_chunk import TagChunk, TagChunkType
from .comment_pipeline import PLCCommentPipeline

logger = logging.getLogger(__name__)

class TagMCPTools(Enum):
    """Enumeration of available tag analysis MCP tools"""
    INDEX_TAG_CSV = "index_tag_csv"
    SEARCH_TAGS = "search_tags"
    FIND_DEVICE = "find_device"
    GET_MODULE_TAGS = "get_module_tags"
    FIND_I_O_POINT = "find_i_o_point"
    ANALYZE_I_O_USAGE = "analyze_i_o_usage"
    FIND_RELATED_TAGS = "find_related_tags"
    GET_DEVICE_OVERVIEW = "get_device_overview"
    GET_SAFETY_TAGS = "get_safety_tags"
    GET_MOTOR_TAGS = "get_motor_tags"
    GET_SENSOR_TAGS = "get_sensor_tags"
    GET_UNCOMMENTED_TAGS = "get_uncommented_tags"
    GET_TAG_REASONING_CONTEXT = "get_tag_reasoning_context"
    GENERATE_COMMENT_DELIVERABLES = "generate_comment_deliverables"
    MANAGE_COMMENT_MEMORY = "manage_comment_memory"

class TagMCPIntegration:
    """
    MCP integration for tag analysis tools enabling semantic search
    through Studio 5000 tag CSV exports
    """
    
    def __init__(self, vector_db: TagVectorDatabase = None):
        self.vector_db = vector_db or TagVectorDatabase()
        self.parser = CSVTagParser()
        self.comment_pipeline = PLCCommentPipeline()
        self.initialized = False
        
        # Index status
        self.indexed_files = {}
    
    async def initialize(self, force_rebuild: bool = False):
        """Initialize the tag analysis system"""
        if self.initialized and not force_rebuild:
            return
        
        try:
            logger.info("Initializing tag MCP integration...")
            
            # Load any cached vector database
            if not force_rebuild:
                self.vector_db._load_from_cache()
            
            self.initialized = True
            logger.info("Tag MCP integration initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize tag MCP integration: {e}")
            raise
    
    async def index_tag_csv(self, csv_path: str, force_rebuild: bool = False) -> Dict[str, Any]:
        """
        Index Studio 5000 tag CSV export for semantic search
        
        Args:
            csv_path: Path to CSV file exported from Studio 5000
            force_rebuild: Force rebuild even if cached
            
        Returns:
            Dictionary with indexing results
        """
        try:
            logger.info(f"Starting indexing of tag CSV: {csv_path}")
            
            if not Path(csv_path).exists():
                return {
                    'success': False,
                    'error': f'CSV file not found: {csv_path}'
                }
            
            # Parse the CSV file
            tag_chunks = self.parser.parse_tag_csv(csv_path)
            
            if not tag_chunks:
                return {
                    'success': False,
                    'error': 'No tags found in CSV file'
                }
            
            # Build vector database
            self.vector_db.build_tag_database(tag_chunks, force_rebuild)
            
            # Get statistics
            stats = self.parser.get_statistics()
            file_name = Path(csv_path).name
            
            # Update indexed files status
            self.indexed_files[file_name] = {
                'path': csv_path,
                'indexed_at': asyncio.get_event_loop().time(),
                'tag_count': len(tag_chunks),
                'statistics': stats
            }
            
            return {
                'success': True,
                'file_name': file_name,
                'tags_indexed': len(tag_chunks),
                'statistics': stats,
                'message': f'Successfully indexed {len(tag_chunks)} tags from {file_name}'
            }
            
        except Exception as e:
            logger.error(f"Error indexing tag CSV {csv_path}: {e}")
            return {
                'success': False,
                'error': f'Indexing failed: {str(e)}'
            }
    
    async def search_tags(self, query: str, category_filter: str = None,
                         chunk_type_filter: str = None, limit: int = 20) -> Dict[str, Any]:
        """
        Semantic search within tag database
        
        Args:
            query: Search query
            category_filter: Filter by device category (VFD, Safety, DI, DO, etc.)
            chunk_type_filter: Filter by chunk type
            limit: Maximum results to return
            
        Returns:
            Dictionary with search results
        """
        try:
            # Convert chunk_type_filter string to enum if provided
            chunk_type_enum = None
            if chunk_type_filter:
                try:
                    chunk_type_enum = TagChunkType(chunk_type_filter.lower())
                except ValueError:
                    return {
                        'success': False,
                        'error': f'Invalid chunk type: {chunk_type_filter}'
                    }
            
            # Perform search
            results = self.vector_db.search_tags(
                query, limit, 
                category_filter=category_filter,
                chunk_type_filter=chunk_type_enum
            )
            
            # Convert results to serializable format
            search_results = []
            for result in results:
                search_results.append({
                    'tag_name': result.tag_name,
                    'type': result.chunk_type.value,
                    'description': result.description,
                    'function': result.function,
                    'category': result.category,
                    'score': result.score,
                    'device_info': {
                        'module_type': result.device_info.module_type,
                        'rack': result.device_info.rack,
                        'slot': result.device_info.slot,
                        'channel': result.device_info.channel,
                        'local_address': result.device_info.local_address,
                        'device_category': result.device_info.device_category,
                        'connection_type': result.device_info.connection_type
                    },
                    'i_o_address': result.i_o_address,
                    'related_tags': result.related_tags[:5],  # Limit for JSON size
                    'metadata': {k: v for k, v in result.metadata.items() 
                               if isinstance(v, (str, int, float, bool))}
                })
            
            return {
                'success': True,
                'query': query,
                'results_count': len(search_results),
                'results': search_results,
                'filters_applied': {
                    'category': category_filter,
                    'chunk_type': chunk_type_filter
                }
            }
            
        except Exception as e:
            logger.error(f"Error searching tags: {e}")
            return {
                'success': False,
                'error': f'Search failed: {str(e)}'
            }
    
    async def find_device(self, device_description: str, device_type: str = None) -> Dict[str, Any]:
        """
        Find specific devices by description or function
        
        Args:
            device_description: Description of device to find
            device_type: Optional device type filter
            
        Returns:
            Dictionary with matching devices
        """
        try:
            results = self.vector_db.find_device_by_description(device_description, device_type)
            
            devices = []
            for result in results:
                devices.append({
                    'tag_name': result.tag_name,
                    'description': result.description,
                    'function': result.function,
                    'score': result.score,
                    'location': {
                        'rack': result.device_info.rack,
                        'slot': result.device_info.slot,
                        'module_type': result.device_info.module_type
                    },
                    'i_o_address': result.i_o_address,
                    'related_tags': result.related_tags[:3]
                })
            
            return {
                'success': True,
                'device_description': device_description,
                'device_type': device_type,
                'devices_found': len(devices),
                'devices': devices
            }
            
        except Exception as e:
            logger.error(f"Error finding device: {e}")
            return {
                'success': False,
                'error': f'Device search failed: {str(e)}'
            }
    
    async def get_module_tags(self, rack: int, slot: int) -> Dict[str, Any]:
        """
        Get all tags for a specific module (rack/slot)
        
        Args:
            rack: Rack number
            slot: Slot number
            
        Returns:
            Dictionary with module tags
        """
        try:
            results = self.vector_db.get_tags_by_module(rack, slot)
            
            module_tags = []
            module_info = None
            
            for result in results:
                tag_info = {
                    'tag_name': result.tag_name,
                    'description': result.description,
                    'function': result.function,
                    'category': result.category,
                    'i_o_address': result.i_o_address,
                    'connection_type': result.device_info.connection_type
                }
                module_tags.append(tag_info)
                
                # Capture module info from first result
                if module_info is None:
                    module_info = {
                        'rack': rack,
                        'slot': slot,
                        'module_type': result.device_info.module_type,
                        'device_category': result.device_info.device_category
                    }
            
            return {
                'success': True,
                'module_info': module_info,
                'tag_count': len(module_tags),
                'tags': module_tags
            }
            
        except Exception as e:
            logger.error(f"Error getting module tags: {e}")
            return {
                'success': False,
                'error': f'Module query failed: {str(e)}'
            }
    
    async def find_i_o_point(self, address_pattern: str = None, description: str = None) -> Dict[str, Any]:
        """
        Find specific I/O points by address or description
        
        Args:
            address_pattern: I/O address pattern to search for
            description: Description to search for
            
        Returns:
            Dictionary with matching I/O points
        """
        try:
            results = self.vector_db.find_i_o_point(address_pattern, description)
            
            i_o_points = []
            for result in results:
                i_o_points.append({
                    'tag_name': result.tag_name,
                    'description': result.description,
                    'function': result.function,
                    'i_o_address': result.i_o_address,
                    'location': {
                        'rack': result.device_info.rack,
                        'slot': result.device_info.slot,
                        'channel': result.device_info.channel
                    },
                    'device_info': {
                        'module_type': result.device_info.module_type,
                        'device_category': result.device_info.device_category,
                        'connection_type': result.device_info.connection_type
                    }
                })
            
            return {
                'success': True,
                'search_criteria': {
                    'address_pattern': address_pattern,
                    'description': description
                },
                'points_found': len(i_o_points),
                'i_o_points': i_o_points
            }
            
        except Exception as e:
            logger.error(f"Error finding I/O point: {e}")
            return {
                'success': False,
                'error': f'I/O point search failed: {str(e)}'
            }
    
    async def analyze_i_o_usage(self) -> Dict[str, Any]:
        """
        Analyze I/O usage and capacity across the system
        
        Returns:
            Dictionary with I/O usage analysis
        """
        try:
            analysis = self.vector_db.analyze_i_o_usage()
            
            return {
                'success': True,
                'analysis': analysis,
                'summary': {
                    'total_tags': analysis['total_tags'],
                    'safety_tags': analysis['safety_analysis']['total_safety_tags'],
                    'motor_tags': analysis['motor_analysis']['total_motor_tags'],
                    'sensor_tags': analysis['sensor_analysis']['total_sensor_tags'],
                    'modules_in_use': len(analysis['module_utilization']),
                    'device_categories': len(analysis['by_device_category'])
                }
            }
            
        except Exception as e:
            logger.error(f"Error analyzing I/O usage: {e}")
            return {
                'success': False,
                'error': f'I/O analysis failed: {str(e)}'
            }
    
    async def find_related_tags(self, tag_name: str, relationship_type: str = "all") -> Dict[str, Any]:
        """
        Find tags related to a given tag
        
        Args:
            tag_name: Tag name to find relationships for
            relationship_type: Type of relationship ('all', 'functional', 'physical')
            
        Returns:
            Dictionary with related tags
        """
        try:
            results = self.vector_db.find_related_tags(tag_name, relationship_type)
            
            related_tags = []
            for result in results:
                related_tags.append({
                    'tag_name': result.tag_name,
                    'description': result.description,
                    'function': result.function,
                    'relationship_score': result.score,
                    'location': {
                        'rack': result.device_info.rack,
                        'slot': result.device_info.slot
                    },
                    'device_category': result.device_info.device_category
                })
            
            return {
                'success': True,
                'source_tag': tag_name,
                'relationship_type': relationship_type,
                'related_count': len(related_tags),
                'related_tags': related_tags
            }
            
        except Exception as e:
            logger.error(f"Error finding related tags: {e}")
            return {
                'success': False,
                'error': f'Related tags search failed: {str(e)}'
            }
    
    async def get_device_overview(self, category_filter: str = None) -> Dict[str, Any]:
        """
        Get comprehensive overview of devices in the system
        
        Args:
            category_filter: Optional category filter
            
        Returns:
            Dictionary with device overview
        """
        try:
            overview = self.vector_db.get_device_overview(category_filter)
            
            return {
                'success': True,
                'category_filter': category_filter,
                'overview': overview
            }
            
        except Exception as e:
            logger.error(f"Error getting device overview: {e}")
            return {
                'success': False,
                'error': f'Device overview failed: {str(e)}'
            }
    
    async def get_safety_tags(self) -> Dict[str, Any]:
        """Get all safety-related tags"""
        return await self.search_tags("safety emergency estop", chunk_type_filter="safety_tag", limit=50)
    
    async def get_motor_tags(self) -> Dict[str, Any]:
        """Get all motor control tags"""
        return await self.search_tags("motor drive vfd conveyor", chunk_type_filter="motor_tag", limit=50)
    
    async def get_sensor_tags(self) -> Dict[str, Any]:
        """Get all sensor tags"""
        return await self.search_tags("sensor photoeye proximity switch", chunk_type_filter="sensor_tag", limit=50)

    def _get_comment_pipeline(self) -> PLCCommentPipeline:
        import importlib
        from . import comment_pipeline
        importlib.reload(comment_pipeline)
        return comment_pipeline.PLCCommentPipeline()

    async def get_uncommented_tags(self, file_path: str, scope_filter: Optional[str] = None) -> Dict[str, Any]:
        """Scan L5X or ACD for tags missing comments or descriptions."""
        try:
            pipeline = self._get_comment_pipeline()
            res = pipeline.get_uncommented_tags(file_path, scope_filter)
            res["success"] = True
            return res
        except Exception as e:
            logger.error(f"Error scanning uncommented tags: {e}")
            return {"success": False, "error": str(e)}

    async def get_tag_reasoning_context(self, tag_name: str, file_path: str) -> Dict[str, Any]:
        """Extract rich context, rungs, logic snippets, and adjacent tag comments for tag reasoning."""
        try:
            pipeline = self._get_comment_pipeline()
            res = pipeline.get_tag_reasoning_context(tag_name, file_path)
            res["success"] = True
            return res
        except Exception as e:
            logger.error(f"Error getting tag reasoning context for {tag_name}: {e}")
            return {"success": False, "error": str(e)}

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
        """Generate Studio 5000 deliverables (Comment_Delta.CSV, comment_review_report.html,
        decisions.json, comment_memory.json, and optionally an updated .ACD project file)."""
        try:
            # Derive the project name from the caller-supplied artifact rather than
            # hardcoding a specific project; fall back to the output folder name.
            if not project_name:
                source_for_name = target_acd or file_path or work_packet_path or decisions_path or output_dir
                if source_for_name:
                    project_name = Path(str(source_for_name)).stem
            pipeline = self._get_comment_pipeline()
            res = pipeline.generate_deliverables(
                decisions=decisions,
                output_dir=output_dir,
                project_name=project_name,
                file_path=file_path,
                edit_acd=edit_acd,
                target_acd=target_acd,
                decisions_path=decisions_path,
                work_packet_path=work_packet_path,
            )
            res["success"] = True
            return res
        except Exception as e:
            logger.error(f"Error generating comment deliverables: {e}")
            return {"success": False, "error": str(e)}

    async def manage_comment_memory(
        self, file_path: str, memory_file_path: str, decisions_to_save: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Track granular routine/tag hashes to skip unchanged routines and incrementally save decisions."""
        try:
            pipeline = self._get_comment_pipeline()
            res = pipeline.manage_incremental_memory(file_path, memory_file_path, decisions_to_save)
            res["success"] = True
            return res
        except Exception as e:
            logger.error(f"Error managing comment memory: {e}")
            return {"success": False, "error": str(e)}

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
        """Build a typed dependency graph, propagate comment facts to a fixed
        point, and emit deliverables only from the converged state."""
        try:
            from comment_graph.config import AnalysisRequest
            from comment_graph.orchestrator import analyze_comment_graph as run_analysis

            request = AnalysisRequest.from_dict(
                {
                    "file_path": file_path,
                    "reference_path": reference_path,
                    "generate_deliverables": generate_deliverables,
                    "output_dir": output_dir,
                    "memory_file_path": memory_file_path,
                    "user_seeds": user_seeds or [],
                    "config": config,
                    "edit_acd": edit_acd,
                    "target_acd": target_acd,
                }
            )
            # The orchestrator owns the full lifecycle, including rendering
            # deliverables (via DeliverablesBridge -> PLCCommentPipeline, no reload).
            result = await run_analysis(request)
            res = result.to_dict()
            res["success"] = True
            self._attach_pipeline_guidance(res, file_path)
            return res
        except Exception as e:
            logger.error(f"Error analyzing comment graph for {file_path}: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _attach_pipeline_guidance(res: Dict[str, Any], file_path: str) -> None:
        """Embed explicit next-step guidance in the analyze result so the model
        follows the canonical pipeline (resolve escalations from logic, then
        render) instead of hand-authoring or skipping. See the FEAT-002 tracking
        issue (#15) and docs/acd_comment_writer_spec.md."""
        requests = res.get("assistance_requests") or []
        n = len(requests)
        auto = len(res.get("decisions") or [])
        steps = [
            f"{auto} evidence-backed decisions were produced automatically; "
            f"{n} assistance_requests still need YOU to resolve them from routine logic.",
        ]
        if n:
            steps += [
                "Do NOT skip, drop, or fabricate assistance_requests, and do NOT hand-author a "
                "comment set that ignores them.",
                f"For each assistance_request, call get_tag_reasoning_context(tag_name=<entity>, "
                f"file_path='{file_path}') and read the rungs to author a specific comment. "
                "Prefix low-confidence text with 'Candidate: '.",
            ]
        steps.append(
            "Combine the automatic `decisions` with the ones you author, then call "
            "generate_comment_deliverables(decisions=<combined>, output_dir=<dir>, "
            f"file_path='{file_path}') to emit Comment_Delta.CSV + comment_review_report.html "
            "+ decisions.json + comment_memory.json (all four)."
        )
        steps.append(
            "Set edit_acd=True on generate_comment_deliverables only if an updated .ACD is also required."
        )
        res["next_steps"] = steps
        res["decision_schema"] = {
            "TYPE": "'COMMENT' for an operand comment, or 'Tag' for a tag description",
            "SCOPE": "controller name (e.g. THAWROOM)",
            "NAME": "full operand path (e.g. N101[20].1) or tag name (e.g. Fan01_DriveStatus)",
            "PROPOSED_DESCRIPTION": "human comment; prefix 'Candidate: ' when confidence is LOW",
            "CONFIDENCE": "HIGH | MEDIUM | LOW",
            "STATUS": "inferred",
            "RATIONALE": "why, citing the rung(s)/evidence used",
        }
        res["decision_example"] = {
            "TYPE": "COMMENT", "SCOPE": "THAWROOM", "NAME": "N101[20].1",
            "PROPOSED_DESCRIPTION": "Thawing Room 2 Master System Enable / Active Run State Flag",
            "CONFIDENCE": "HIGH", "STATUS": "inferred",
            "RATIONALE": "Latched in Cell_1_Temperature_Control_4 rung 0; gates Fan 11-20 and glycol pump start.",
        }

    async def generate_program_comments(
        self,
        acd_path: str,
        routine_filter: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Orchestrate the whole comment pipeline in one call.

        Runs analyze_comment_graph (step 1) and, in a single L5X pass, pre-fetches
        the routine-logic reasoning context for every escalated operand/tag so the
        model can author one description per item and hand the combined set to
        generate_comment_deliverables — no per-operand tool round-trips.

        Returns a work packet: `auto_decisions` (evidence-backed, ready to pass
        through), `to_resolve` (each escalation + its rungs + a pre-filled
        `draft_decision` skeleton), plus `next_steps`/schema/example. The full
        packet is also written to work_packet.json alongside the ACD.
        """
        try:
            import re
            from comment_graph.config import AnalysisRequest
            from comment_graph.orchestrator import analyze_comment_graph as run_analysis

            # 1. Run the deterministic analysis (no deliverables yet).
            request = AnalysisRequest.from_dict({
                "file_path": acd_path,
                "generate_deliverables": False,
                "config": config,
            })
            result = await run_analysis(request)
            analysis = result.to_dict()
            auto_decisions = analysis.get("decisions") or []
            assistance = analysis.get("assistance_requests") or []

            # 2. Parse the L5X once and index every rung for batched reasoning.
            pipeline = self._get_comment_pipeline()
            try:
                l5x_path = pipeline.resolve_l5x_path(acd_path)
            except Exception as exc:
                return {
                    "success": False,
                    "error": f"Reasoning context needs an L5X next to the ACD: {exc}. "
                             f"Run convert_acd_to_l5x first, then retry.",
                }
            root = pipeline.parse_l5x_tree(l5x_path)

            controller_el = root.find(".//Controller")
            controller = (controller_el.attrib.get("Name") if controller_el is not None
                          else l5x_path.stem)

            tag_desc_map: Dict[str, str] = {}
            for tag in root.findall(".//Tag"):
                nm = tag.attrib.get("Name", "")
                c = tag.find("Comment")
                if nm and c is not None and c.text:
                    tag_desc_map[nm] = c.text.strip()

            # Collect rungs (optionally filtered to one routine).
            rungs = []  # (routine, rung_number, text, comment)
            ident_pat = re.compile(r"[A-Za-z_][A-Za-z0-9_:\.\[\]]*")
            for program in root.findall(".//Programs/Program"):
                for routine in program.findall(".//Routine"):
                    rout_name = routine.attrib.get("Name", "")
                    if routine_filter and rout_name != routine_filter:
                        continue
                    rll = routine.find("RLLContent")
                    if rll is None:
                        continue
                    for rung in rll.findall("Rung"):
                        te = rung.find("Text")
                        text = te.text.strip() if (te is not None and te.text) else ""
                        ce = rung.find("Comment")
                        rc = ce.text.strip() if (ce is not None and ce.text) else ""
                        if text:
                            rungs.append((rout_name, rung.attrib.get("Number", ""), text, rc))

            # 3. Build entity -> rung references in a single pass over rungs.
            entities = []
            for req in assistance:
                # entity ids look like "op:N101[20].1"; strip only the op: prefix
                raw = str(req.get("entity", ""))
                ent = raw[3:] if raw.startswith("op:") else raw
                if ent:
                    entities.append((ent, req.get("ambiguity", "")))

            patterns = {
                ent: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(ent) + r"(?![A-Za-z0-9_:\.\[\]])")
                for ent, _ in entities
            }
            refs: Dict[str, list] = {ent: [] for ent, _ in entities}
            MAX_RUNGS = 6
            for rout_name, rnum, text, rc in rungs:
                for ent, pat in patterns.items():
                    if len(refs[ent]) >= MAX_RUNGS:
                        continue
                    if pat.search(text):
                        adj = []
                        seen = set()
                        for token in ident_pat.findall(text):
                            base = token.split(".")[0].split("[")[0]
                            if base != ent.split(".")[0].split("[")[0] and base not in seen and len(base) > 1:
                                seen.add(base)
                                d = tag_desc_map.get(base) or tag_desc_map.get(token) or ""
                                if d:
                                    adj.append({"name": token, "description": d})
                        refs[ent].append({
                            "routine": rout_name, "rung_number": rnum,
                            "ladder_logic": text, "rung_comment": rc,
                            "adjacent_tags": adj[:10],
                        })

            # 4. Assemble to_resolve items (each with a pre-filled skeleton).
            def make_item(ent, ambiguity):
                rr = refs.get(ent, [])
                is_operand = ("[" in ent) or ("." in ent) or (":" in ent)
                return {
                    "entity": ent,
                    "ambiguity": ambiguity,
                    "occurrence_count": len(rr),
                    "rung_references": rr,
                    "draft_decision": {
                        "TYPE": "COMMENT" if is_operand else "Tag",
                        "SCOPE": controller if is_operand else "",
                        "NAME": ent,
                        "PROPOSED_DESCRIPTION": "",  # <-- author from rung_references; 'Candidate: ' if low confidence
                        "CONFIDENCE": "",
                        "STATUS": "inferred",
                        "RATIONALE": "",
                    },
                }

            all_items = [make_item(ent, amb) for ent, amb in entities]
            # Items with no rung evidence sort last (hardest / likely data-table only).
            all_items.sort(key=lambda x: (x["occurrence_count"] == 0, x["entity"]))
            page = all_items[offset:offset + limit] if limit else all_items[offset:]

            # 5. Persist the full work packet next to the ACD for reference.
            from pathlib import Path as _Path
            out_dir = _Path(acd_path).with_suffix("").parent / f"{_Path(acd_path).stem}_deliverables"
            out_dir.mkdir(parents=True, exist_ok=True)
            packet = {
                "controller": controller,
                "auto_decisions": auto_decisions,
                "to_resolve": all_items,
            }
            packet_path = out_dir / "work_packet.json"
            packet_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")

            # P4: Return compact response envelope to avoid MCP tool output truncation
            return {
                "success": True,
                "controller": controller,
                "routine_filter": routine_filter,
                "counts": {
                    "auto_decisions": len(auto_decisions),
                    "to_resolve_total": len(all_items),
                    "to_resolve_returned": len(page),
                    "with_logic_evidence": sum(1 for i in all_items if i["occurrence_count"]),
                    "no_logic_evidence": sum(1 for i in all_items if not i["occurrence_count"]),
                },
                "page": {"offset": offset, "limit": limit, "has_more": offset + len(page) < len(all_items)},
                "sample_to_resolve": page[:3],
                "sample_auto_decisions": auto_decisions[:3],
                "work_packet_path": str(packet_path),
                "next_steps": [
                    f"Read work_packet_path ('{packet_path}') to inspect all to_resolve items and fill draft_decision's "
                    "PROPOSED_DESCRIPTION (and CONFIDENCE/RATIONALE). Prefix low-confidence text with 'Candidate: '.",
                    f"Once draft descriptions are authored in work_packet.json, call generate_comment_deliverables(work_packet_path='{packet_path}') "
                    "to render all four deliverables (Comment_Delta.CSV, comment_review_report.html, decisions.json, comment_memory.json).",
                ],
                "decision_schema": {
                    "TYPE": "'COMMENT' for an operand, 'Tag' for a tag description",
                    "SCOPE": "controller name for COMMENT rows (e.g. " + controller + "); blank for Tag",
                    "NAME": "full operand path or tag name",
                    "PROPOSED_DESCRIPTION": "human comment; 'Candidate: ' prefix when low confidence",
                    "CONFIDENCE": "HIGH | MEDIUM | LOW",
                    "STATUS": "inferred",
                    "RATIONALE": "why, citing the rung(s) used",
                },
            }
        except Exception as e:
            logger.error(f"Error in generate_program_comments for {acd_path}: {e}")
            return {"success": False, "error": str(e)}

    def get_available_tools(self) -> Dict[str, str]:
        """Get list of available MCP tools"""
        return {
            tool.value: f"Tag analysis tool: {tool.value.replace('_', ' ').title()}"
            for tool in TagMCPTools
        }
    
    def get_indexing_status(self) -> Dict[str, Any]:
        """Get status of indexed files"""
        return {
            'indexed_files': self.indexed_files,
            'total_files': len(self.indexed_files),
            'system_ready': len(self.indexed_files) > 0
        }
