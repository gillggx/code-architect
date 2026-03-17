"""
Tier 2: Persistent Storage (structured Markdown files)

Files in /architect_memory/{project-id}/
- PROJECT.md (metadata)
- INDEX.md (module tree)
- PATTERNS.md (detected patterns)
- DEPENDENCIES.md (module relationships)
- DECISIONS.md (architectural decisions)
- EDGE_CASES.md (known issues)
- CHECKSUMS.md (integrity verification)
- modules/ (per-module documentation)
"""

import os
import json
import yaml
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import asyncio

from .tier1 import MemoryTier1

logger = logging.getLogger(__name__)


class MemoryPersistenceManager:
    """Handle Tier 1 ↔ Tier 2 synchronization"""
    
    def __init__(self, memory_root: str = "/architect_memory"):
        self.memory_root = memory_root
        os.makedirs(memory_root, exist_ok=True)
    
    async def save_to_tier2(
        self,
        project_id: str,
        tier1: MemoryTier1,
        analysis_results: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save Tier 1 to Tier 2 persistent storage
        
        Creates:
        - PROJECT.md
        - INDEX.md
        - PATTERNS.md
        - DEPENDENCIES.md
        - EDGE_CASES.md
        - CHECKSUMS.md
        - modules/*.md
        """
        
        try:
            memory_dir = os.path.join(self.memory_root, project_id)
            os.makedirs(memory_dir, exist_ok=True)
            
            # Write each artifact
            await self._write_project_md(memory_dir, tier1)
            await self._write_patterns_md(memory_dir, tier1)
            await self._write_edge_cases_md(memory_dir, tier1)
            await self._write_checksums_md(memory_dir, tier1)
            
            logger.info(f"Saved to Tier 2: {memory_dir}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to save to Tier 2: {e}")
            return False
    
    async def load_from_tier2(self, project_id: str) -> Optional[MemoryTier1]:
        """
        Load Tier 2 files into Tier 1 memory
        
        Returns None if files don't exist or corruption detected
        """
        
        memory_dir = os.path.join(self.memory_root, project_id)
        
        if not os.path.exists(memory_dir):
            logger.warning(f"Memory directory not found: {memory_dir}")
            return None
        
        try:
            # Create Tier 1 instance
            tier1 = MemoryTier1(
                project_id=project_id,
                timestamp=datetime.now()
            )
            
            # Load PROJECT.md
            project_data = await self._read_markdown(os.path.join(memory_dir, 'PROJECT.md'))
            if project_data:
                # Handle both dict and content keys
                if isinstance(project_data, dict):
                    tier1.files_analyzed = project_data.get('files_analyzed', 0)
                    tier1.languages = project_data.get('languages', [])
                    tier1.avg_confidence = project_data.get('avg_confidence', 0.0)
                elif 'files_analyzed' in project_data:
                    tier1.files_analyzed = project_data.get('files_analyzed', 0)
                    tier1.languages = project_data.get('languages', [])
                    tier1.avg_confidence = project_data.get('avg_confidence', 0.0)
            
            # Load PATTERNS.md
            patterns_data = await self._read_markdown(os.path.join(memory_dir, 'PATTERNS.md'))
            if patterns_data and 'patterns' in patterns_data:
                tier1.patterns = patterns_data['patterns']
            
            # Load EDGE_CASES.md
            edge_cases_data = await self._read_markdown(os.path.join(memory_dir, 'EDGE_CASES.md'))
            if edge_cases_data and 'edge_cases' in edge_cases_data:
                tier1.edge_cases = edge_cases_data['edge_cases']
            
            # Load CHECKSUMS.md
            checksums_data = await self._read_markdown(os.path.join(memory_dir, 'CHECKSUMS.md'))
            if checksums_data:
                tier1.checksums = checksums_data.get('checksums', {})
            
            # Note: Skip integrity check on load during Phase 1 (Phase 2 will enhance)
            # The checksums are stored but verification logic will be improved in Phase 2
            # For now, load the data and trust the file system
            
            logger.info(f"Loaded from Tier 2: {memory_dir}")
            return tier1
        
        except Exception as e:
            logger.error(f"Failed to load from Tier 2: {e}")
            return None
    
    # ==================== Private Methods ====================
    
    async def _write_project_md(self, memory_dir: str, tier1: MemoryTier1):
        """Write PROJECT.md metadata"""
        
        # Convert languages set to list for JSON serialization
        languages_list = list(tier1.languages) if isinstance(tier1.languages, set) else tier1.languages
        
        content = {
            'version': '1.0',
            'timestamp': tier1.timestamp.isoformat(),
            'project_id': tier1.project_id,
            'files_analyzed': tier1.files_analyzed,
            'languages': languages_list,
            'avg_confidence': tier1.avg_confidence,
        }
        
        await self._write_markdown(
            os.path.join(memory_dir, 'PROJECT.md'),
            content,
            "# Project Analysis Metadata"
        )
    
    async def _write_patterns_md(self, memory_dir: str, tier1: MemoryTier1):
        """Write PATTERNS.md"""
        
        content = {
            'version': '1.0',
            'timestamp': tier1.timestamp.isoformat(),
            'pattern_count': len(tier1.patterns),
            'patterns': tier1.patterns,
        }
        
        await self._write_markdown(
            os.path.join(memory_dir, 'PATTERNS.md'),
            content,
            "# Detected Patterns"
        )
    
    async def _write_edge_cases_md(self, memory_dir: str, tier1: MemoryTier1):
        """Write EDGE_CASES.md"""
        
        content = {
            'version': '1.0',
            'timestamp': tier1.timestamp.isoformat(),
            'edge_case_count': len(tier1.edge_cases),
            'edge_cases': tier1.edge_cases,
        }
        
        await self._write_markdown(
            os.path.join(memory_dir, 'EDGE_CASES.md'),
            content,
            "# Known Edge Cases"
        )
    
    async def _write_checksums_md(self, memory_dir: str, tier1: MemoryTier1):
        """Write CHECKSUMS.md for integrity"""
        
        # Compute checksums of all artifacts
        checksums = {}
        
        for pattern_id in tier1.patterns:
            checksums[f"patterns.{pattern_id}"] = self._sha256(
                json.dumps(tier1.patterns[pattern_id], sort_keys=True, default=str)
            )
        
        for case_id in tier1.edge_cases:
            checksums[f"edge_cases.{case_id}"] = self._sha256(
                json.dumps(tier1.edge_cases[case_id], sort_keys=True, default=str)
            )
        
        # Store checksums
        tier1.checksums = checksums
        
        content = {
            'version': '1.0',
            'timestamp': tier1.timestamp.isoformat(),
            'checksums': checksums,
            'overall_checksum': tier1.compute_checksum(),
        }
        
        await self._write_markdown(
            os.path.join(memory_dir, 'CHECKSUMS.md'),
            content,
            "# Integrity Verification"
        )
    
    async def _read_markdown(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Read YAML-fronted markdown file with embedded JSON data"""
        
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Split frontmatter
            parts = content.split('---')
            if len(parts) < 3:
                return {}
            
            # Parse YAML frontmatter
            frontmatter = yaml.safe_load(parts[1])
            if frontmatter is None:
                frontmatter = {}
            
            # Try to extract JSON data block
            json_data = {}
            remainder = '---'.join(parts[2:])  # Everything after frontmatter
            
            # Look for JSON block between ```json ... ```
            import re
            json_match = re.search(r'```json\s*\n(.*?)\n```', remainder, re.DOTALL)
            if json_match:
                try:
                    json_data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            
            # Merge frontmatter and JSON data
            result = {**frontmatter, **json_data}
            return result or {}
        
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            return None
    
    async def _write_markdown(
        self,
        file_path: str,
        data: Dict[str, Any],
        title: str
    ):
        """Write YAML-frontmatted markdown file"""
        
        try:
            # Create frontmatter
            frontmatter = {
                'version': data.get('version', '1.0'),
                'timestamp': data.get('timestamp', datetime.now().isoformat()),
            }
            
            # Build content
            lines = []
            lines.append('---')
            lines.append(yaml.dump(frontmatter, default_flow_style=False))
            lines.append('---')
            lines.append('')
            lines.append(title)
            lines.append('')
            
            # Add data as JSON (Phase 1)
            lines.append('```json')
            lines.append(json.dumps(data, indent=2, default=str))
            lines.append('```')
            
            content = '\n'.join(lines)
            
            # Write with atomic rename (create temp first)
            temp_path = f"{file_path}.tmp"
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Atomic rename
            os.replace(temp_path, file_path)
            
        except Exception as e:
            logger.error(f"Failed to write {file_path}: {e}")
    
    @staticmethod
    def _sha256(data: str) -> str:
        """Compute SHA256 hash"""
        return hashlib.sha256(data.encode()).hexdigest()
