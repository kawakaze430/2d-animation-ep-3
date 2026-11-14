"""Undo/redo-safe semantic timeline changes; editor and CLI share this API.

Commands are JSON data, not executable Python. Every operation is transactional:
invalid edits leave current state, saved file and history unchanged. Asset and
license metadata are managed via explicit import methods, not general pointers.
"""
from __future__ import annotations

from copy import deepcopy

from .schema import validate_project


def _parts(pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Edit path must be a JSON pointer")
    raw = pointer[1:].split("/")
    parts = []
    for element in raw:
        if "~" in element:
            # Only two escape sequences are legal in a JSON pointer.
            check = element.replace("~0", "").replace("~1", "")
            if "~" in check:
                raise ValueError("Invalid JSON pointer escape")
            element = element.replace("~1", "/").replace("~0", "~")
        if not element or element in ("__proto__", "constructor", "prototype"):
            raise ValueError("Invalid editor path component")
        parts.append(element)
    if parts[0] not in ("scenes", "motion_library"):
        raise PermissionError("Editor can modify only scenes or motion library")
    return parts


def _index(value, key, *, allow_end=False):
    if not isinstance(value, list):
        raise ValueError("Expected array for numeric pointer")
    if key == "-" and allow_end:
        return len(value)
    if not key.isdigit() or (key.startswith("0") and key != "0"):
        raise ValueError("Array index must be decimal")
    i = int(key)
    if not 0 <= i < len(value) + int(allow_end):
        raise IndexError("Editor array index outside range")
    return i


def _resolve_parent(doc, path):
    parts = _parts(path)
    cur = doc
    for key in parts[:-1]:
        if isinstance(cur, list):
            cur = cur[_index(cur, key)]
        elif isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            raise KeyError(f"Editor path does not exist: {key}")
    return cur, parts[-1]


def apply_command(doc, command):
    """Pure function returning a new validated project; never mutates input."""
    if isinstance(command, dict) and command.get("op") == "batch":
        if set(command) != {"op", "commands"} or not isinstance(command["commands"], list) or not 1 <= len(command["commands"]) <= 20:
            raise ValueError("Batch edit must have 1..20 commands")
        updated = deepcopy(doc)
        for item in command["commands"]:
            updated = apply_command(updated, item)
        return updated
    if not isinstance(command, dict) or set(command) - {"op", "path", "value"}:
        raise ValueError("Expected JSON editor command op/path/value")
    op = command.get("op")
    if op not in ("set", "add", "remove"):
        raise ValueError("Unsupported edit operation")
    if op != "remove" and "value" not in command:
        raise ValueError("Editing a value requires a JSON value")
    new = deepcopy(doc)
    parent, key = _resolve_parent(new, command.get("path"))
    if isinstance(parent, dict):
        if op == "add":
            if key in parent:
                raise FileExistsError("Use set to replace an existing field")
            parent[key] = deepcopy(command["value"])
        elif op == "set":
            if key not in parent:
                raise KeyError("Use add to create a new field")
            parent[key] = deepcopy(command["value"])
        else:
            if key not in parent:
                raise KeyError("Cannot remove missing key")
            del parent[key]
    elif isinstance(parent, list):
        index = _index(parent, key, allow_end=(op == "add"))
        if op == "add":
            parent.insert(index, deepcopy(command["value"]))
        elif op == "set":
            parent[index] = deepcopy(command["value"])
        else:
            parent.pop(index)
    else:
        raise ValueError("Cannot edit scalar parent")
    return validate_project(new)


class EditSession:
    """Bounded undo/redo for GUI and CLI. Call save() for atomic persistence."""

    def __init__(self, project, *, history_limit=100):
        if not 1 <= history_limit <= 1000:
            raise ValueError("Undo history limit out of range")
        self.project = project
        self.limit = history_limit
        self.undo_stack = []
        self.redo_stack = []

    @property
    def can_undo(self):
        return bool(self.undo_stack)

    @property
    def can_redo(self):
        return bool(self.redo_stack)

    def apply(self, command, *, save=True):
        next_doc = apply_command(self.project.doc, command)
        before = deepcopy(self.project.doc)
        self.project.doc = next_doc
        try:
            if save:
                self.project.save()
        except Exception:
            self.project.doc = before
            raise
        self.undo_stack.append(before)
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        return deepcopy(self.project.doc)

    def undo(self, *, save=True):
        if not self.can_undo:
            raise ValueError("Nothing to undo")
        previous = self.undo_stack[-1]
        current = self.project.doc
        self.project.doc = deepcopy(previous)
        try:
            if save:
                self.project.save()
        except Exception:
            self.project.doc = current
            raise
        self.undo_stack.pop()
        self.redo_stack.append(current)
        return deepcopy(self.project.doc)

    def redo(self, *, save=True):
        if not self.can_redo:
            raise ValueError("Nothing to redo")
        next_doc = self.redo_stack[-1]
        current = self.project.doc
        self.project.doc = deepcopy(next_doc)
        try:
            if save:
                self.project.save()
        except Exception:
            self.project.doc = current
            raise
        self.redo_stack.pop()
        self.undo_stack.append(current)
        return deepcopy(self.project.doc)
