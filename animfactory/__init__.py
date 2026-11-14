"""Independent Python 2D animation product core (project format v1).

Engine bridge reuses the existing Pillow IK/rendering without Episode03 scripts
or a provider API. There is no implied license change.
"""
from .project import Project
from .editing import EditSession, apply_command
from .schema import FORMAT, VERSION, empty_project, validate_project

__all__ = ["Project", "EditSession", "apply_command",
           "FORMAT", "VERSION", "empty_project", "validate_project"]
