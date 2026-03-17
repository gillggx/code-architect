"""
Incremental Analysis

Tracks file modification times and fingerprints to detect changes since the
last project analysis. Only re-analyzes files that have changed, significantly
reducing analysis time for large projects.

Design:
- A FileSnapshot records mtime + size + sha256 (configurable).
- The ChangeDetector compares current file state against a stored snapshot.
- Changed files are returned for re-analysis; unchanged files are skipped.
- Snapshots persist alongside Tier-2 memory as SNAPSHOTS.json.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_SNAPSHOT_FILE = "SNAPSHOTS.json"

# Extensions to track (mirrors the parser registry)
_TRACKED_EXTENSIONS: Set[str] = {
    ".py", ".cpp", ".cc", ".cxx", ".hpp", ".h",
    ".java", ".js", ".ts", ".jsx", ".html", ".htm", ".sql",
}

_SKIP_DIRS: Set[str] = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".pytest_cache", "build", "dist", ".mypy_cache",
}


@dataclass
class FileSnapshot:
    """Represents the state of a single file at analysis time."""
    path: str
    mtime: float          # os.path.getmtime result
    size: int             # File size in bytes
    checksum: str = ""    # SHA256 (populated if use_checksum=True)

    def is_same_as_disk(self, use_checksum: bool = False) -> bool:
        """
        Check if the file on disk matches this snapshot.

        Fast path: compare mtime + size.
        Thorough path: compare SHA256 hash (use_checksum=True).
        """
        if not os.path.exists(self.path):
            return False
        try:
            stat = os.stat(self.path)
            if stat.st_mtime != self.mtime or stat.st_size != self.size:
                return False
            if use_checksum and self.checksum:
                return _sha256_file(self.path) == self.checksum
            return True
        except OSError:
            return False


@dataclass
class ProjectSnapshot:
    """Collection of FileSnapshots for all tracked files in a project."""
    project_path: str
    analyzed_at: float            # Unix timestamp of last analysis
    file_snapshots: Dict[str, FileSnapshot] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "project_path": self.project_path,
            "analyzed_at": self.analyzed_at,
            "file_snapshots": {
                path: asdict(snap)
                for path, snap in self.file_snapshots.items()
            },
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectSnapshot":
        snapshots = {
            path: FileSnapshot(**snap)
            for path, snap in data.get("file_snapshots", {}).items()
        }
        return cls(
            project_path=data["project_path"],
            analyzed_at=data["analyzed_at"],
            file_snapshots=snapshots,
            metadata=data.get("metadata", {}),
        )


class ChangeDetector:
    """
    Detects which project files have changed since the last analysis.

    Usage::

        detector = ChangeDetector()
        snapshot = await detector.snapshot_project("/path/to/project")
        changed, new, deleted = await detector.detect_changes("/path/to/project", old_snapshot)
        await detector.save_snapshot(snapshot, "/memory/project-id")
    """

    def __init__(self, use_checksum: bool = False) -> None:
        """
        Args:
            use_checksum: If True, use SHA256 in addition to mtime/size.
                          Slower but detects timestamp-preserving modifications.
        """
        self.use_checksum = use_checksum

    # ------------------------------------------------------------------
    # Snapshot creation
    # ------------------------------------------------------------------

    async def snapshot_project(
        self,
        project_path: str,
        extensions: Optional[Set[str]] = None,
    ) -> ProjectSnapshot:
        """
        Walk a project and create a snapshot of all tracked files.

        Args:
            project_path: Root directory of the project.
            extensions: Set of file extensions to track. Defaults to _TRACKED_EXTENSIONS.

        Returns:
            ProjectSnapshot with current file states.
        """
        import time

        exts = extensions or _TRACKED_EXTENSIONS
        loop = asyncio.get_event_loop()
        snapshot_data = await loop.run_in_executor(
            None, self._walk_project, project_path, exts
        )
        return ProjectSnapshot(
            project_path=project_path,
            analyzed_at=time.time(),
            file_snapshots=snapshot_data,
        )

    def _walk_project(
        self, project_path: str, extensions: Set[str]
    ) -> Dict[str, FileSnapshot]:
        """Synchronous filesystem walk (run in executor)."""
        snapshots: Dict[str, FileSnapshot] = {}

        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in files:
                if Path(fname).suffix.lower() not in extensions:
                    continue
                fpath = os.path.join(root, fname)
                try:
                    stat = os.stat(fpath)
                    checksum = (
                        _sha256_file(fpath) if self.use_checksum else ""
                    )
                    snapshots[fpath] = FileSnapshot(
                        path=fpath,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                        checksum=checksum,
                    )
                except OSError as exc:
                    logger.debug("Cannot stat %s: %s", fpath, exc)

        return snapshots

    # ------------------------------------------------------------------
    # Change detection
    # ------------------------------------------------------------------

    async def detect_changes(
        self,
        project_path: str,
        old_snapshot: ProjectSnapshot,
        extensions: Optional[Set[str]] = None,
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Compare current project state against an old snapshot.

        Args:
            project_path: Project root directory.
            old_snapshot: Snapshot from the previous analysis.
            extensions: Extensions to track.

        Returns:
            Tuple of (changed, new, deleted) file path lists.
        """
        current = await self.snapshot_project(project_path, extensions)
        return self._diff_snapshots(old_snapshot, current)

    def diff_snapshots(
        self, old: ProjectSnapshot, new: ProjectSnapshot
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Diff two snapshots without filesystem access.

        Returns:
            (changed, added, deleted) lists of file paths.
        """
        return self._diff_snapshots(old, new)

    def _diff_snapshots(
        self, old: ProjectSnapshot, new: ProjectSnapshot
    ) -> Tuple[List[str], List[str], List[str]]:
        old_paths = set(old.file_snapshots.keys())
        new_paths = set(new.file_snapshots.keys())

        added = sorted(new_paths - old_paths)
        deleted = sorted(old_paths - new_paths)

        changed: List[str] = []
        for path in old_paths & new_paths:
            old_snap = old.file_snapshots[path]
            new_snap = new.file_snapshots[path]
            if old_snap.mtime != new_snap.mtime or old_snap.size != new_snap.size:
                changed.append(path)
            elif self.use_checksum and old_snap.checksum and new_snap.checksum:
                if old_snap.checksum != new_snap.checksum:
                    changed.append(path)

        return sorted(changed), added, deleted

    # ------------------------------------------------------------------
    # Files needing re-analysis
    # ------------------------------------------------------------------

    def get_files_to_analyze(
        self,
        old_snapshot: Optional[ProjectSnapshot],
        new_snapshot: ProjectSnapshot,
    ) -> List[str]:
        """
        Return files that need (re-)analysis.

        If old_snapshot is None (first run), returns all tracked files.
        Otherwise returns changed + new files.
        """
        if old_snapshot is None:
            return sorted(new_snapshot.file_snapshots.keys())

        changed, added, _ = self._diff_snapshots(old_snapshot, new_snapshot)
        return sorted(set(changed + added))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def save_snapshot(self, snapshot: ProjectSnapshot, directory: str) -> None:
        """Save snapshot to a JSON file in directory."""
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, _SNAPSHOT_FILE)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_json, path, snapshot.to_dict())
        logger.info("Snapshot saved: %d files → %s", len(snapshot.file_snapshots), path)

    async def load_snapshot(self, directory: str) -> Optional[ProjectSnapshot]:
        """Load snapshot from directory. Returns None if not found."""
        path = os.path.join(directory, _SNAPSHOT_FILE)
        if not os.path.exists(path):
            return None
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, _read_json, path)
            return ProjectSnapshot.from_dict(data)
        except Exception as exc:
            logger.error("Failed to load snapshot from %s: %s", path, exc)
            return None

    def describe_changes(
        self, changed: List[str], added: List[str], deleted: List[str]
    ) -> str:
        """Human-readable summary of detected changes."""
        parts = []
        if changed:
            parts.append(f"{len(changed)} modified")
        if added:
            parts.append(f"{len(added)} new")
        if deleted:
            parts.append(f"{len(deleted)} deleted")
        return ", ".join(parts) if parts else "no changes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: str) -> str:
    """Compute SHA256 hash of a file (read in 64 KB chunks)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


__all__ = ["ChangeDetector", "FileSnapshot", "ProjectSnapshot"]
