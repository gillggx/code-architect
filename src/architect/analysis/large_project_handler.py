"""
Large Project Support for Code Architect Agent - Phase 3

Handles analysis of 500+ file projects with stratified sampling,
parallelization, and confidence degradation for extrapolated findings.

Version: 3.0
Status: PRODUCTION
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Literal, Set
from pathlib import Path
import os
import random
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ProjectSize:
    """Project size classification"""
    total_files: int
    files_by_language: Dict[str, int]
    size_category: Literal["small", "medium", "large", "xlarge"]
    estimated_analysis_time_sec: float
    
    @property
    def requires_sampling(self) -> bool:
        """Large projects need stratified sampling"""
        return self.total_files > 200
    
    @property
    def parallel_workers(self) -> int:
        """Number of concurrent workers based on project size"""
        if self.total_files < 50:
            return 2
        elif self.total_files < 200:
            return 4
        elif self.total_files < 500:
            return 8
        else:
            return 16


@dataclass
class SamplingStrategy:
    """Stratified sampling configuration"""
    total_files: int
    target_sample_size: int = 200  # Analyze 200 files for detailed analysis
    sampling_ratio: float = 0.8    # Sample 80%, extrapolate 20%
    min_per_language: int = 5      # Minimum files per language
    stratification_by_language: bool = True
    
    def calculate_sample(self, files_by_language: Dict[str, int]) -> Dict[str, int]:
        """
        Calculate stratified sample respecting language distribution
        
        Returns dict of {language: sample_size}
        """
        if not self.stratification_by_language:
            return {'all': min(self.target_sample_size, self.total_files)}
        
        total_sampled = 0
        samples = {}
        
        # First pass: allocate minimum per language
        for lang, count in files_by_language.items():
            min_sample = min(self.min_per_language, count)
            samples[lang] = min_sample
            total_sampled += min_sample
        
        # Second pass: distribute remaining budget proportionally
        remaining_budget = self.target_sample_size - total_sampled
        remaining_files = self.total_files - total_sampled
        
        if remaining_budget > 0:
            for lang, count in files_by_language.items():
                # Proportion of remaining files
                proportion = (count - samples.get(lang, 0)) / remaining_files
                additional = int(proportion * remaining_budget)
                samples[lang] = samples.get(lang, 0) + additional
                total_sampled += additional
        
        logger.info(f"Sampling strategy: {samples} (total: {total_sampled})")
        return samples


@dataclass
class SampleMetadata:
    """Metadata about which files were sampled"""
    sampled_files: Set[str]
    extrapolated_files: Set[str]
    sampling_ratio: float
    confidence_degradation: float = 0.1  # Reduce confidence by 10% for extrapolated
    
    @property
    def coverage(self) -> float:
        """Percentage of files directly analyzed"""
        total = len(self.sampled_files) + len(self.extrapolated_files)
        return len(self.sampled_files) / total if total > 0 else 0.0


class ProjectSizeDetector:
    """Detect project size and categorize"""
    
    @staticmethod
    def detect(project_path: str) -> ProjectSize:
        """Analyze project structure and categorize size"""
        
        path = Path(project_path)
        files_by_language = {}
        total_files = 0
        
        # Count files by language
        language_extensions = {
            'python': {'.py'},
            'cpp': {'.cpp', '.cc', '.cxx', '.h', '.hpp'},
            'java': {'.java'},
            'javascript': {'.js', '.jsx'},
            'typescript': {'.ts', '.tsx'},
            'sql': {'.sql'},
            'html': {'.html', '.htm'},
            'other': set()
        }
        
        for file_path in path.rglob('*'):
            if not file_path.is_file():
                continue
            
            # Skip common non-source directories
            if any(skip in str(file_path) for skip in [
                '.git', '__pycache__', 'node_modules', '.venv', 'venv',
                'dist', 'build', '.next', 'target'
            ]):
                continue
            
            suffix = file_path.suffix.lower()
            total_files += 1
            
            # Classify by language
            found = False
            for lang, extensions in language_extensions.items():
                if lang != 'other' and suffix in extensions:
                    files_by_language[lang] = files_by_language.get(lang, 0) + 1
                    found = True
                    break
            
            if not found:
                files_by_language['other'] = files_by_language.get('other', 0) + 1
        
        # Categorize size
        if total_files < 50:
            size_category = "small"
            estimated_time = 10
        elif total_files < 200:
            size_category = "medium"
            estimated_time = 30
        elif total_files < 500:
            size_category = "large"
            estimated_time = 60
        else:
            size_category = "xlarge"
            estimated_time = 120
        
        return ProjectSize(
            total_files=total_files,
            files_by_language=files_by_language,
            size_category=size_category,
            estimated_analysis_time_sec=estimated_time
        )


class StratifiedFileSampler:
    """Select files for analysis using stratified random sampling"""
    
    def __init__(self, seed: Optional[int] = None):
        self.seed = seed
        if seed is not None:
            random.seed(seed)
    
    def sample_files(
        self,
        project_path: str,
        strategy: SamplingStrategy,
        files_by_language: Dict[str, int]
    ) -> Tuple[List[str], SampleMetadata]:
        """
        Select stratified sample of files for analysis
        
        Returns:
        - List of sampled file paths
        - Metadata about sampling (what was extrapolated)
        """
        
        # Collect all source files by language
        all_files_by_lang = self._collect_files_by_language(project_path)
        
        # Calculate sample sizes per language
        sample_sizes = strategy.calculate_sample(files_by_language)
        
        # Sample files
        sampled = []
        sampled_set = set()
        
        for lang, target_count in sample_sizes.items():
            if lang not in all_files_by_lang:
                continue
            
            lang_files = all_files_by_lang[lang]
            
            # Random sample without replacement
            sample_count = min(target_count, len(lang_files))
            lang_sample = random.sample(lang_files, sample_count)
            
            sampled.extend(lang_sample)
            sampled_set.update(lang_sample)
        
        # Track extrapolated files
        all_files = set()
        for files in all_files_by_lang.values():
            all_files.update(files)
        
        extrapolated = all_files - sampled_set
        
        metadata = SampleMetadata(
            sampled_files=sampled_set,
            extrapolated_files=extrapolated,
            sampling_ratio=len(sampled_set) / len(all_files) if all_files else 1.0
        )
        
        logger.info(
            f"Sampled {len(sampled)} files, "
            f"extrapolated {len(extrapolated)} files "
            f"(ratio: {metadata.sampling_ratio:.1%})"
        )
        
        return sampled, metadata
    
    @staticmethod
    def _collect_files_by_language(project_path: str) -> Dict[str, List[str]]:
        """Collect all source files organized by language"""
        
        files_by_lang = {}
        
        language_extensions = {
            'python': {'.py'},
            'cpp': {'.cpp', '.cc', '.cxx', '.h', '.hpp'},
            'java': {'.java'},
            'javascript': {'.js', '.jsx'},
            'typescript': {'.ts', '.tsx'},
            'sql': {'.sql'},
            'html': {'.html', '.htm'},
        }
        
        for file_path in Path(project_path).rglob('*'):
            if not file_path.is_file():
                continue
            
            # Skip common directories
            if any(skip in str(file_path) for skip in [
                '.git', '__pycache__', 'node_modules', '.venv', 'venv',
                'dist', 'build', '.next', 'target'
            ]):
                continue
            
            suffix = file_path.suffix.lower()
            
            for lang, extensions in language_extensions.items():
                if suffix in extensions:
                    if lang not in files_by_lang:
                        files_by_lang[lang] = []
                    files_by_lang[lang].append(str(file_path))
                    break
        
        return files_by_lang


class LargeProjectHandler:
    """
    Handle analysis of large projects (500+ files)
    
    Strategy:
    1. Detect project size
    2. Create stratified sampling strategy
    3. Sample 200 representative files for detailed analysis
    4. Extrapolate findings to remaining files
    5. Degrade confidence for extrapolated findings
    """
    
    def __init__(self):
        self.size_detector = ProjectSizeDetector()
        self.sampler = StratifiedFileSampler()
        logger.info("LargeProjectHandler initialized")
    
    async def prepare_large_project_analysis(
        self,
        project_path: str,
        max_sample_size: int = 200
    ) -> Tuple[List[str], ProjectSize, SampleMetadata]:
        """
        Prepare analysis for large project
        
        Returns:
        - Files to analyze (sampled)
        - Project size information
        - Sampling metadata
        """
        
        logger.info(f"Detecting project size: {project_path}")
        
        # Step 1: Detect size
        size_info = self.size_detector.detect(project_path)
        logger.info(f"Project size: {size_info.size_category} "
                   f"({size_info.total_files} files)")
        
        # Step 2: Create sampling strategy
        if size_info.requires_sampling:
            strategy = SamplingStrategy(
                total_files=size_info.total_files,
                target_sample_size=max_sample_size,
                sampling_ratio=0.8
            )
        else:
            # Small project: analyze all files
            strategy = SamplingStrategy(
                total_files=size_info.total_files,
                target_sample_size=size_info.total_files
            )
        
        # Step 3: Sample files
        files_to_analyze, metadata = self.sampler.sample_files(
            project_path,
            strategy,
            size_info.files_by_language
        )
        
        logger.info(f"Analysis plan: {len(files_to_analyze)} files to analyze, "
                   f"coverage: {metadata.coverage:.1%}")
        
        return files_to_analyze, size_info, metadata
    
    def get_parallel_workers(self, project_size: ProjectSize) -> int:
        """Determine number of parallel workers"""
        return project_size.parallel_workers
    
    def should_use_sampling(self, project_size: ProjectSize) -> bool:
        """Check if sampling is needed"""
        return project_size.requires_sampling
    
    def calculate_confidence_adjustment(
        self,
        is_sampled: bool,
        sampling_metadata: Optional[SampleMetadata] = None
    ) -> float:
        """
        Calculate confidence adjustment factor
        
        Sampled files: confidence *= 1.0
        Extrapolated files: confidence *= 0.9
        
        Returns adjustment factor
        """
        if not is_sampled:
            return 1.0
        
        if sampling_metadata:
            # Reduce confidence by degradation amount
            return 1.0 - sampling_metadata.confidence_degradation
        
        return 0.9  # Default: 10% reduction for extrapolated
    
    def estimate_analysis_time(self, size_info: ProjectSize) -> float:
        """Estimate total analysis time in seconds"""
        
        base_time = size_info.estimated_analysis_time_sec
        
        # If sampling is needed, reduce time proportionally
        if size_info.requires_sampling:
            sampling_ratio = 200 / size_info.total_files
            return base_time * sampling_ratio
        
        return base_time


class ExtrapolationEngine:
    """
    Extrapolate analysis findings to non-sampled files
    
    Strategy:
    - Findings from sampled files apply to similar files
    - Patterns detected in sample likely present in population
    - Adjust confidence downward for extrapolated findings
    """
    
    def extrapolate_patterns(
        self,
        sampled_patterns: List,
        sampling_metadata: SampleMetadata
    ) -> Tuple[List, List]:
        """
        Extrapolate patterns to all files
        
        Returns:
        - Sampled patterns (high confidence)
        - Extrapolated patterns (medium confidence)
        """
        
        extrapolated = []
        
        for pattern in sampled_patterns:
            # Create extrapolated version with reduced confidence
            extrapolated_pattern = pattern.copy()
            extrapolated_pattern.confidence *= (
                1.0 - sampling_metadata.confidence_degradation
            )
            extrapolated_pattern.extrapolated = True
            extrapolated_pattern.coverage = sampling_metadata.coverage
            
            extrapolated.append(extrapolated_pattern)
        
        return sampled_patterns, extrapolated
    
    def extrapolate_dependencies(
        self,
        sampled_deps: Dict,
        sampling_metadata: SampleMetadata
    ) -> Dict:
        """
        Extrapolate dependencies to all files
        
        Mark extrapolated dependencies with lower confidence
        """
        
        extrapolated_deps = {}
        
        for dep_id, dep_info in sampled_deps.items():
            extrapolated_info = dep_info.copy()
            extrapolated_info['extrapolated'] = True
            extrapolated_info['confidence'] = dep_info.get('confidence', 1.0) * (
                1.0 - sampling_metadata.confidence_degradation
            )
            extrapolated_deps[dep_id] = extrapolated_info
        
        return extrapolated_deps


def create_large_project_config(
    project_path: str,
    max_workers: Optional[int] = None
) -> Dict:
    """
    Create configuration for analyzing large project
    
    Returns dict with:
    - files_to_analyze: List of sampled files
    - parallel_workers: Number of concurrent workers
    - project_size: Size category
    - estimated_time: Estimated analysis time
    - sampling_metadata: Sampling information
    """
    
    handler = LargeProjectHandler()
    
    files, size_info, metadata = asyncio.run(
        handler.prepare_large_project_analysis(project_path)
    )
    
    return {
        'files_to_analyze': files,
        'total_files': size_info.total_files,
        'files_by_language': size_info.files_by_language,
        'project_size': size_info.size_category,
        'parallel_workers': max_workers or size_info.parallel_workers,
        'estimated_time_sec': size_info.estimated_analysis_time_sec,
        'sampling_metadata': metadata,
        'requires_sampling': size_info.requires_sampling,
    }
