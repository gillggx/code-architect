"""Multi-project management system"""

from .manager import (
    ProjectManager,
    ProjectMetadata,
    ProjectMemory,
    SessionState,
    MultiProjectContextManager,
    create_project_manager,
)

__all__ = [
    'ProjectManager',
    'ProjectMetadata',
    'ProjectMemory',
    'SessionState',
    'MultiProjectContextManager',
    'create_project_manager',
]
