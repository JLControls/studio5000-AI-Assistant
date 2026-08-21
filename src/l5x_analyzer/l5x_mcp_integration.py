#!/usr/bin/env python3
"""
L5X MCP Integration

Integrates the L5X Vector Database and SDK-powered analyzer with the MCP server,
providing tools for semantic search and intelligent modification of large L5X files.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from enum import Enum

from .l5x_vector_db import L5XVectorDatabase, L5XSearchResult
from .sdk_powered_analyzer import SDKPoweredL5XAnalyzer
from .l5x_chunk import L5XChunkType
from .l5x_fact_accessor import get_tag_value, describe_aoi, decode_aoi_call
from .tag_cross_reference import find_tag_references as _find_tag_references

logger = logging.getLogger(__name__)

class L5XMCPTools(Enum):
    """Enumeration of available L5X analysis MCP tools"""
    INDEX_EXPORTED_L5X_FILES = "index_exported_l5x_files"  # NEW: Direct L5X file indexing
    INDEX_ACD_PROJECT = "index_acd_project"  # OLD: Disabled ACD indexing
    SEARCH_L5X_CONTENT = "search_l5x_content"
    FIND_INSERTION_POINT = "find_insertion_point"
    SMART_INSERT_LOGIC = "smart_insert_logic"
    EXTRACT_ROUTINE_CONTENT = "extract_routine_content"
    ANALYZE_ROUTINE_STRUCTURE = "analyze_routine_structure"
    FIND_RELATED_COMPONENTS = "find_related_components"
    GET_PROJECT_OVERVIEW = "get_project_overview"
    BATCH_ROUTINE_ANALYSIS = "batch_routine_analysis"
    GET_TAG_VALUE = "get_tag_value"  # issue #28: configured L5X value accessor
    DESCRIBE_AOI = "describe_aoi"  # issue #28: ordered AOI parameter definition
    DECODE_AOI_CALL = "decode_aoi_call"  # issue #28: AOI-call operand bindings
    FIND_TAG_REFERENCES = "find_tag_references"  # issue #26: deterministic where-used

class L5XSDKMCPIntegration:
    """
    MCP integration for L5X analysis tools combining vector database 
    with SDK-powered operations for production-scale L5X files
    """
    
    def __init__(self, vector_db: L5XVectorDatabase = None):
        self.vector_db = vector_db or L5XVectorDatabase()
        self.sdk_analyzer = SDKPoweredL5XAnalyzer()
        self.initialized = False
        
        # Import AI assistant for logic generation
        self._code_assistant = None
    
    def _get_code_assistant(self):
        """Lazy load code assistant to avoid circular imports"""
        if self._code_assistant is None:
            try:
                from ..ai_assistant.code_assistant import CodeAssistant
                self._code_assistant = CodeAssistant()
            except ImportError:
                logger.warning("Code assistant not available - logic generation disabled")
        return self._code_assistant
    
    async def initialize(self, force_rebuild: bool = False):
        """Initialize the L5X analysis system"""
        if self.initialized and not force_rebuild:
            return
        
        try:
            logger.info("Initializing L5X SDK MCP integration...")
            
            # Load any cached vector database
            if not force_rebuild:
                self.vector_db._load_from_cache()
            
            self.initialized = True
            logger.info("L5X SDK MCP integration initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize L5X MCP integration: {e}")
            raise
    
    def index_exported_l5x_files(self, l5x_directory: str, force_rebuild: bool = False) -> Dict[str, Any]:
        """
        Index EXPORTED L5X files directly (no ACD/SDK opening needed)
        
        Args:
            l5x_directory: Directory containing exported L5X files
            force_rebuild: Force rebuild even if cached
            
        Returns:
            Dictionary with indexing results
        """
        try:
            logger.info(f"Indexing exported L5X files from: {l5x_directory}")
            
            if not Path(l5x_directory).exists():
                return {
                    'success': False,
                    'error': f'L5X directory not found: {l5x_directory}'
                }
            
            # Index the exported L5X files directly
            success = self.vector_db.index_exported_l5x_files(l5x_directory, force_rebuild)
            
            if success:
                # Get indexing statistics
                project_name = Path(l5x_directory).name
                stats = self.vector_db.indexed_projects.get(project_name, {})
                
                return {
                    'success': True,
                    'project_name': project_name,
                    'files_indexed': stats.get('file_count', 0),
                    'chunks_created': stats.get('chunk_count', 0),
                    'message': f'✅ Successfully indexed exported L5X files from {project_name}'
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to index L5X files - check logs for details'
                }
                
        except Exception as e:
            logger.error(f"Error indexing L5X files from {l5x_directory}: {e}")
            return {
                'success': False,
                'error': f'Exception during L5X indexing: {str(e)}'
            }

    async def index_acd_project(self, acd_path: str, routines_to_index: List[str] = None,
                              force_rebuild: bool = False) -> Dict[str, Any]:
        """
        Index ACD/L5K project for semantic search
        
        Args:
            acd_path: Path to ACD or L5K file
            routines_to_index: Specific routines to index (None for all)
            force_rebuild: Force rebuild even if cached
            
        Returns:
            Dictionary with indexing results
        """
        try:
            logger.info(f"Starting indexing of project: {acd_path}")
            
            if not Path(acd_path).exists():
                return {
                    'success': False,
                    'error': f'Project file not found: {acd_path}'
                }
            
            # Index the project
            success = await self.vector_db.index_acd_project(
                acd_path, routines_to_index, force_rebuild
            )
            
            if success:
                # Get indexing statistics
                project_name = Path(acd_path).stem
                stats = self.vector_db.indexed_projects.get(project_name, {})
                
                return {
                    'success': True,
                    'project_name': project_name,
                    'routines_indexed': stats.get('routine_count', 0),
                    'chunks_created': stats.get('chunk_count', 0),
                    'message': f'Successfully indexed {project_name}'
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to index project - check logs for details'
                }
                
        except Exception as e:
            logger.error(f"Error indexing project {acd_path}: {e}")
            return {
                'success': False,
                'error': f'Exception during indexing: {str(e)}'
            }
    
    async def search_l5x_content(self, query: str, file_filter: str = None,
                               component_type: str = None, limit: int = 20) -> Dict[str, Any]:
        """
        Semantic search within indexed L5X content
        
        Args:
            query: Search query
            file_filter: Filter by project file name
            component_type: Filter by component type (routine, rung, udt, etc.)
            limit: Maximum results to return
            
        Returns:
            Dictionary with search results
        """
        try:
            # Convert component_type string to enum if provided
            chunk_types = None
            if component_type:
                try:
                    chunk_types = [L5XChunkType(component_type.lower())]
                except ValueError:
                    return {
                        'success': False,
                        'error': f'Invalid component type: {component_type}'
                    }
            
            # Perform search with lower threshold for broader results
            results = self.vector_db.search_l5x_content(
                query, limit, score_threshold=0.05, chunk_types=chunk_types
            )
            
            # Filter by file if requested
            if file_filter:
                results = [r for r in results if file_filter.lower() in r.file_path.lower()]
            
            # Convert results to serializable format
            search_results = []
            for result in results:
                search_results.append({
                    'chunk_id': result.chunk_id,
                    'type': result.chunk_type.value,
                    'name': result.name,
                    'description': result.description,
                    'score': result.score,
                    'content_preview': result.content[:200] + '...' if len(result.content) > 200 else result.content,
                    'location': {
                        'file_path': result.location.file_path,
                        'xpath': result.location.xpath,
                        'routine': result.location.parent_routine,
                        'program': result.location.parent_program,
                        'rung_number': result.location.rung_number
                    },
                    'insertion_hints': result.insertion_hints
                })
            
            return {
                'success': True,
                'query': query,
                'results_count': len(search_results),
                'results': search_results
            }
            
        except Exception as e:
            logger.error(f"Error searching L5X content: {e}")
            return {
                'success': False,
                'error': f'Search failed: {str(e)}'
            }
    
    async def find_insertion_point(self, new_logic_description: str, target_routine: str,
                                 target_file: str = None) -> Dict[str, Any]:
        """
        Find optimal location to insert new ladder logic
        
        Args:
            new_logic_description: Description of logic to insert
            target_routine: Target routine name
            target_file: Optional target file filter
            
        Returns:
            Dictionary with insertion recommendations
        """
        try:
            # Find optimal insertion point
            position, confidence = self.vector_db.find_optimal_insertion_point(
                new_logic_description, target_routine
            )
            
            # Get related context
            context_search = f"similar to {new_logic_description} in {target_routine}"
            context_results = self.vector_db.search_l5x_content(
                context_search, limit=3, 
                chunk_types=[L5XChunkType.LADDER_RUNG]
            )
            
            # Get routine analysis
            routine_analysis = self.vector_db.get_routine_analysis(target_routine)
            
            return {
                'success': True,
                'recommended_position': position,
                'confidence_score': confidence,
                'target_routine': target_routine,
                'reasoning': f'Insert at rung {position} based on semantic similarity analysis',
                'context_rungs': [
                    {
                        'rung_number': r.location.rung_number,
                        'description': r.description,
                        'similarity_score': r.score
                    }
                    for r in context_results if r.location.parent_routine == target_routine
                ],
                'routine_info': routine_analysis
            }
            
        except Exception as e:
            logger.error(f"Error finding insertion point: {e}")
            return {
                'success': False,
                'error': f'Failed to find insertion point: {str(e)}'
            }
    
    async def smart_insert_logic(self, l5x_file_path: str, routine_name: str, 
                               logic_description: str, program_name: str = "MainProgram",
                               insertion_mode: str = "optimal") -> Dict[str, Any]:
        """
        Generate ladder logic and directly insert it into L5X file
        
        Args:
            l5x_file_path: Path to L5X file to modify
            routine_name: Target routine name
            logic_description: Description of logic to generate
            program_name: Parent program name
            insertion_mode: 'optimal' or 'end'
            
        Returns:
            Dictionary with insertion results
        """
        try:
            logger.info(f"Directly inserting logic into L5X file: {l5x_file_path}")
            
            # Verify L5X file exists
            from pathlib import Path
            import xml.etree.ElementTree as ET
            import shutil
            import time
            
            l5x_path = Path(l5x_file_path)
            if not l5x_path.exists():
                return {
                    'success': False,
                    'error': f'L5X file not found: {l5x_file_path}'
                }
            
            # Create backup of original file
            backup_path = l5x_path.with_suffix(f'.backup_{int(time.time())}.L5X')
            shutil.copy2(l5x_path, backup_path)
            logger.info(f"Created backup: {backup_path}")
            
            # Generate ladder logic using AI assistant
            code_assistant = self._get_code_assistant()
            if not code_assistant:
                return {
                    'success': False,
                    'error': 'Code generation not available - AI assistant not loaded'
                }
            
            generated_logic = code_assistant.generate_ladder_logic(logic_description)
            if not generated_logic or 'ladder_logic' not in generated_logic:
                return {
                    'success': False,
                    'error': 'Failed to generate ladder logic - check logic description'
                }
            
            logic_text = generated_logic['ladder_logic']
            logger.info(f"Generated logic: {logic_text}")
            
            # Parse L5X file and find target routine
            tree = ET.parse(l5x_path)
            root = tree.getroot()
            
            # Find the target routine
            routine_xpath = f".//Program[@Name='{program_name}']//Routine[@Name='{routine_name}']"
            routine_elem = root.find(routine_xpath)
            
            if routine_elem is None:
                return {
                    'success': False,
                    'error': f'Routine {routine_name} not found in program {program_name}'
                }
            
            # Find RLLContent section
            rll_content = routine_elem.find('RLLContent')
            if rll_content is None:
                return {
                    'success': False,
                    'error': f'Routine {routine_name} is not a ladder logic routine (no RLLContent)'
                }
            
            # Find insertion point
            existing_rungs = rll_content.findall('Rung')
            if insertion_mode == "optimal":
                # Try to find optimal insertion point using vector database
                try:
                    insertion_point, confidence = self.vector_db.find_optimal_insertion_point(
                        logic_description, routine_name
                    )
                except Exception as e:
                    logger.warning(f"Could not find optimal insertion point: {e}")
                    insertion_point = len(existing_rungs)  # Insert at end
                    confidence = 0.0
            else:
                # Insert at end
                insertion_point = len(existing_rungs)
                confidence = 1.0
            
            # Split generated logic into individual rungs
            logic_lines = [line.strip() for line in logic_text.split('\n') if line.strip()]
            rung_texts = []
            current_rung = ""
            
            for line in logic_lines:
                if line.startswith('//'):
                    continue  # Skip comments for now
                current_rung += line
                if line.endswith(';'):
                    rung_texts.append(current_rung.strip())
                    current_rung = ""
                else:
                    current_rung += " "
            
            # Add any remaining logic as a rung
            if current_rung.strip():
                rung_texts.append(current_rung.strip())
            
            # Renumber existing rungs after insertion point
            for rung in existing_rungs[insertion_point:]:
                old_number = int(rung.get('Number', 0))
                new_number = old_number + len(rung_texts)
                rung.set('Number', str(new_number))
            
            # Create new rung elements and insert them
            inserted_rungs = 0
            for i, rung_text in enumerate(rung_texts):
                new_rung = ET.Element('Rung')
                new_rung.set('Number', str(insertion_point + i))
                new_rung.set('Type', 'N')
                
                # Add comment
                comment_elem = ET.SubElement(new_rung, 'Comment')
                comment_elem.text = f"Generated: {logic_description}"
                
                # Add text content
                text_elem = ET.SubElement(new_rung, 'Text')
                text_elem.text = rung_text
                
                # Insert into RLLContent at correct position
                rll_content.insert(insertion_point + i, new_rung)
                inserted_rungs += 1
            
            # Save the modified L5X file
            tree.write(l5x_path, encoding='UTF-8', xml_declaration=True)
            
            return {
                'success': True,
                'file_modified': str(l5x_path),
                'backup_created': str(backup_path),
                'insertion_details': {
                    'position': insertion_point,
                    'rungs_inserted': inserted_rungs,
                    'insertion_mode': insertion_mode,
                    'confidence_score': confidence
                },
                'generated_content': {
                    'logic_text': logic_text,
                    'rung_count': len(rung_texts),
                    'tags_referenced': generated_logic.get('tags', [])
                },
                'target_info': {
                    'routine_name': routine_name,
                    'program_name': program_name,
                    'description': logic_description
                },
                'message': f'✅ Successfully inserted {inserted_rungs} rungs at position {insertion_point} in {routine_name}'
            }
                
        except Exception as e:
            logger.error(f"Error during smart logic generation: {e}")
            return {
                'success': False,
                'error': f'Logic generation failed: {str(e)}'
            }
    
    async def extract_routine_content(self, acd_path: str, routine_name: str,
                                    program_name: Optional[str] = None, 
                                    output_format: str = "summary") -> Dict[str, Any]:
        """
        Extract specific routine content for analysis using vector database
        
        Args:
            acd_path: Path to ACD/L5K file (for context, not opened)
            routine_name: Routine to extract
            program_name: Optional parent program name to disambiguate identical routine names
            output_format: 'summary', 'full', or 'rungs_only'
            
        Returns:
            Dictionary with extracted content
        """
        try:
            logger.info(f"Extracting routine content for {routine_name} using vector database")
            
            def _is_match(result):
                if result.location.parent_routine != routine_name and result.name != routine_name:
                    return False
                if program_name and result.location.parent_program != program_name:
                    return False
                return True

            # Search for the specific routine in the vector database
            routine_query = f"routine {routine_name}"
            search_results = self.vector_db.search_l5x_content(
                routine_query, limit=100, 
                chunk_types=[L5XChunkType.ROUTINE, L5XChunkType.LADDER_RUNG]
            )
            
            # Filter results to exact routine match
            routine_chunks = []
            rung_chunks = []
            
            for result in search_results:
                if _is_match(result):
                    if result.chunk_type == L5XChunkType.ROUTINE:
                        routine_chunks.append(result)
                    elif result.chunk_type == L5XChunkType.LADDER_RUNG:
                        rung_chunks.append(result)
            
            if not routine_chunks and not rung_chunks:
                # Auto-indexing fallback: if acd_path exists, attempt to index its directory
                path_obj = Path(acd_path)
                l5x_dir = path_obj.parent if path_obj.is_file() else path_obj
                if l5x_dir.exists():
                    logger.info(f"Routine {routine_name} not found in index. Auto-indexing L5X files from {l5x_dir}...")
                    self.index_exported_l5x_files(str(l5x_dir))
                    search_results = self.vector_db.search_l5x_content(
                        routine_query, limit=100, 
                        chunk_types=[L5XChunkType.ROUTINE, L5XChunkType.LADDER_RUNG]
                    )
                    for result in search_results:
                        if _is_match(result):
                            if result.chunk_type == L5XChunkType.ROUTINE:
                                routine_chunks.append(result)
                            elif result.chunk_type == L5XChunkType.LADDER_RUNG:
                                rung_chunks.append(result)

            if not routine_chunks and not rung_chunks:
                scope_info = f" in program {program_name}" if program_name else ""
                return {
                    'success': False,
                    'error': f'Routine {routine_name}{scope_info} not found in indexed content after scanning {acd_path}.'
                }
            
            # Sort rungs by rung number
            rung_chunks.sort(key=lambda x: x.location.rung_number or 0)
            resolved_program = (
                routine_chunks[0].location.parent_program if routine_chunks
                else (rung_chunks[0].location.parent_program if rung_chunks else (program_name or "MainProgram"))
            )
            
            # Format output based on requested format
            if output_format == "summary":
                return {
                    'success': True,
                    'routine_name': routine_name,
                    'program_name': resolved_program,
                    'rung_count': len(rung_chunks),
                    'description': routine_chunks[0].description if routine_chunks else 'No description available',
                    'dependencies': list(set().union(*[result.dependencies for result in routine_chunks + rung_chunks if hasattr(result, 'dependencies')])),
                    'complexity_info': {
                        'total_rungs': len(rung_chunks),
                        'has_routine_metadata': len(routine_chunks) > 0
                    },
                    'file_location': routine_chunks[0].location.file_path if routine_chunks else (rung_chunks[0].location.file_path if rung_chunks else 'Unknown')
                }
            
            elif output_format == "rungs_only":
                rungs = []
                
                for result in rung_chunks:
                    rungs.append({
                        'rung_number': result.location.rung_number,
                        'logic': result.content,
                        'comment': result.description,
                        'score': result.score,
                        'file_path': result.location.file_path
                    })
                
                return {
                    'success': True,
                    'routine_name': routine_name,
                    'program_name': resolved_program,
                    'rungs': rungs,
                    'total_rungs': len(rungs)
                }
            
            else:  # full
                all_chunks = routine_chunks + rung_chunks
                chunks_data = []
                
                for result in all_chunks:
                    chunks_data.append({
                        'id': result.chunk_id,
                        'type': result.chunk_type.value,
                        'name': result.name,
                        'content': result.content,
                        'description': result.description,
                        'score': result.score,
                        'location': {
                            'file_path': result.location.file_path,
                            'xpath': result.location.xpath,
                            'routine': result.location.parent_routine,
                            'program': result.location.parent_program,
                            'rung_number': result.location.rung_number
                        }
                    })
                
                return {
                    'success': True,
                    'routine_name': routine_name,
                    'program_name': resolved_program,
                    'chunks': chunks_data,
                    'total_chunks': len(chunks_data)
                }
                
        except Exception as e:
            logger.error(f"Error extracting routine content: {e}")
            return {
                'success': False,
                'error': f'Extraction failed: {str(e)}'
            }
    
    async def analyze_routine_structure(self, routine_name: str, program_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze structure and complexity of an indexed routine
        
        Args:
            routine_name: Name of routine to analyze
            program_name: Optional program scope to disambiguate routines
            
        Returns:
            Dictionary with analysis results
        """
        try:
            analysis = self.vector_db.get_routine_analysis(routine_name, program_name)
            
            if 'error' in analysis:
                return {
                    'success': False,
                    'error': analysis['error']
                }
            
            return {
                'success': True,
                'analysis': analysis
            }
            
        except Exception as e:
            logger.error(f"Error analyzing routine structure: {e}")
            return {
                'success': False,
                'error': f'Analysis failed: {str(e)}'
            }
    
    async def find_related_components(self, component_name: str, project_filter: str = None,
                                    relationship_type: str = "usage") -> Dict[str, Any]:
        """
        Find components related to a given component
        
        Args:
            component_name: Name of component to find relationships for
            project_filter: Optional project file filter
            relationship_type: Type of relationship ('usage', 'dependency', 'similar')
            
        Returns:
            Dictionary with related components
        """
        try:
            # Relationship results must be based on exact operand references.
            # The old implementation queried FAISS with "uses <tag>" and could
            # report a confident empty result for a heavily used tag.
            cross_reference = await self.find_indexed_tag_references(
                component_name, project_filter
            )
            if not cross_reference.get('success'):
                return cross_reference

            related_components = list(cross_reference.get('references', []))
            return {
                'success': True,
                'primary_component': {'name': component_name, 'type': 'tag'},
                'related_components': related_components,
                'relationship_type': relationship_type,
                'total_found': len(related_components),
                'summary': cross_reference.get('summary', {}),
                'coverage': cross_reference.get('coverage', {}),
            }
            
        except Exception as e:
            logger.error(f"Error finding related components: {e}")
            return {
                'success': False,
                'error': f'Search for related components failed: {str(e)}'
            }
    
    async def get_project_overview(self, acd_path: str) -> Dict[str, Any]:
        """
        Get project overview from indexed vector database content
        
        Args:
            acd_path: Path to ACD/L5K file (for context only)
            
        Returns:
            Dictionary with project overview from indexed data
        """
        try:
            logger.info(f"Getting project overview from vector database for {acd_path}")
            
            # Get overview from vector database indexed projects
            project_name = Path(acd_path).stem
            indexed_projects = self.vector_db.indexed_projects
            
            # Check if we have data for this project
            if project_name not in indexed_projects:
                if not indexed_projects:
                    return {
                        'success': False,
                        'error': (
                            f"Project '{project_name}' is not indexed. No L5X data is "
                            "available; run index_exported_l5x_files or index_acd_project first."
                        )
                    }
                return {
                    'success': False,
                    'error': (
                        f"Project '{project_name}' is not indexed. Run "
                        "index_exported_l5x_files or index_acd_project for this project first."
                    )
                }
            
            project_stats = indexed_projects[project_name]

            # The overview is derived from a deterministic structural walk of the
            # indexed L5X (issue #9), never from a semantic/vector search. If an
            # older cache predates structural capture, require a re-index rather
            # than silently returning recall-limited counts.
            structure = project_stats.get('structure')
            if not structure:
                return {
                    'success': False,
                    'error': (
                        f"Indexed project '{project_name}' has no structural metadata "
                        "(indexed by an older version). Re-index it with "
                        "index_exported_l5x_files (or index_acd_project) to get an "
                        "accurate project overview."
                    )
                }

            programs = list(structure.get('programs', []))
            routine_details = list(structure.get('routines', []))
            udts = list(structure.get('udts', []))
            add_on_instructions = list(structure.get('add_on_instructions', []))
            modules = list(structure.get('modules', []))
            # Preserve the historical `routines` shape (a list of names) for
            # existing callers; routine_details carries full (program, routine)
            # identity so same-named routines stay distinguishable.
            routine_names = sorted({r.get('name') for r in routine_details if r.get('name')})

            return {
                'success': True,
                'project_path': acd_path,
                'project_name': project_name,
                'controller': structure.get('controller'),
                'indexing_stats': {
                    'files_indexed': project_stats.get('file_count', 0),
                    'chunks_created': project_stats.get('chunk_count', 0),
                    'last_indexed': project_stats.get('indexed_at',
                                                      project_stats.get('last_indexed', 'Unknown'))
                },
                'overview': {
                    'program_count': len(programs),
                    'routine_count': len(routine_details),
                    'udt_count': len(udts),
                    'add_on_instruction_count': len(add_on_instructions),
                    'module_count': len(modules)
                },
                'programs': programs,
                'routines': routine_names,
                'routine_details': routine_details,
                'udts': udts,
                # Add-On-Defined types (one per AOI) and the module I/O inventory
                # are surfaced explicitly: AOIs are the type category most often
                # missed, and modules describe how to read un-aliased I/O points.
                'add_on_instructions': add_on_instructions,
                'modules': modules,
                'note': 'Overview derived from a deterministic structural walk of the indexed L5X.'
            }
            
        except Exception as e:
            logger.error(f"Error getting project overview: {e}")
            return {
                'success': False,
                'error': f'Failed to get project overview: {str(e)}'
            }
    
    async def get_tag_value(self, l5x_file_path: str, tag_name: str,
                            member: Optional[str] = None,
                            program_name: Optional[str] = None) -> Dict[str, Any]:
        """Return a tag's configured value(s) from decorated L5X data (issue #28).

        A deterministic structural read: no vector indexing required, so it works
        on a concrete L5X path without calling index_exported_l5x_files first.
        """
        try:
            return get_tag_value(l5x_file_path, tag_name, member, program_name)
        except Exception as e:
            logger.error(f"Error reading tag value: {e}")
            return {'success': False, 'error': f'Failed to read tag value: {str(e)}'}

    async def describe_aoi(self, l5x_file_path: str, aoi_name: str) -> Dict[str, Any]:
        """Return an AOI's ordered parameter definition (issue #28)."""
        try:
            return describe_aoi(l5x_file_path, aoi_name)
        except Exception as e:
            logger.error(f"Error describing AOI: {e}")
            return {'success': False, 'error': f'Failed to describe AOI: {str(e)}'}

    async def decode_aoi_call(self, l5x_file_path: str, routine_name: str,
                              rung_number: int, program_name: Optional[str] = None,
                              aoi_name: Optional[str] = None) -> Dict[str, Any]:
        """Decode a rung's AOI invocation(s) into operand→parameter bindings (issue #28)."""
        try:
            return decode_aoi_call(
                l5x_file_path, routine_name, rung_number, program_name, aoi_name
            )
        except Exception as e:
            logger.error(f"Error decoding AOI call: {e}")
            return {'success': False, 'error': f'Failed to decode AOI call: {str(e)}'}

    async def find_tag_references(self, l5x_file_path: str, tag_name: str,
                                  program_scope: Optional[str] = None) -> Dict[str, Any]:
        """Return deterministic read/write/AOI references from an exported L5X."""
        try:
            return _find_tag_references(l5x_file_path, tag_name, program_scope)
        except Exception as e:
            logger.error("Error finding tag references: %s", e)
            return {
                'success': False,
                'error': f'Failed to find tag references: {str(e)}'
            }

    def _indexed_l5x_paths(self, project_filter: Optional[str] = None) -> List[Path]:
        """Return concrete exported L5X paths represented by index metadata."""
        paths: List[Path] = []
        for stats in self.vector_db.indexed_projects.values():
            raw_path = stats.get('path')
            if not raw_path:
                continue
            path = Path(raw_path)
            if project_filter and project_filter.lower() not in str(path).lower():
                continue
            if path.is_file() and path.suffix.lower() == '.l5x':
                paths.append(path)
            elif path.is_dir():
                paths.extend(sorted(path.glob('*.L5X')))
                paths.extend(sorted(path.glob('*.l5x')))
        return list(dict.fromkeys(paths))

    async def find_indexed_tag_references(self, tag_name: str,
                                          project_filter: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate exact references over exported L5X files in the index."""
        paths = self._indexed_l5x_paths(project_filter)
        if not paths:
            return {
                'success': False,
                'error': (
                    'No exported L5X file is available for deterministic cross-reference. '
                    'Run index_exported_l5x_files first; ACD-only vector indexing does not '
                    'retain an inspectable L5X path.'
                )
            }

        results = [_find_tag_references(path, tag_name) for path in paths]
        failures = [result for result in results if not result.get('success')]
        successes = [result for result in results if result.get('success')]
        if not successes:
            return failures[0] if failures else {
                'success': False,
                'error': f"Tag '{tag_name}' was not found in indexed L5X files."
            }

        references: List[Dict[str, Any]] = []
        warnings: List[str] = []
        skipped: List[Dict[str, Any]] = []
        complete = not failures
        for path, result in zip(paths, results):
            if not result.get('success'):
                warnings.append(f"{path}: {result.get('error', 'cross-reference failed')}")
                continue
            for reference in result.get('references', []):
                reference = dict(reference)
                reference['file_path'] = str(path)
                references.append(reference)
            coverage = result.get('coverage', {})
            complete = complete and bool(coverage.get('complete', False))
            warnings.extend(f"{path}: {warning}" for warning in coverage.get('warnings', []))
            skipped.extend(
                {**item, 'file_path': str(path)}
                for item in coverage.get('routines_skipped', [])
            )

        summary = {
            'reads': sum(r['role'] == 'READ_SOURCE' for r in references),
            'writes': sum(r['role'] == 'WRITE_DESTINATION' for r in references),
            'read_write': sum(r['role'] == 'READ_WRITE' for r in references),
            'aoi_args': sum(r['role'] == 'AOI_ARG' for r in references),
            'unknown': sum(r['role'] == 'UNKNOWN' for r in references),
            'total': len(references),
        }
        return {
            'success': True,
            'tag': tag_name,
            'references': references,
            'summary': summary,
            'coverage': {
                'complete': complete and not warnings and not skipped,
                'files_scanned': len(paths),
                'routines_skipped': skipped,
                'warnings': warnings,
            },
        }

    def get_available_tools(self) -> Dict[str, str]:
        """Get list of available MCP tools"""
        return {
            tool.value: f"L5X analysis tool: {tool.value.replace('_', ' ').title()}"
            for tool in L5XMCPTools
        }
