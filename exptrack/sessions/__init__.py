"""
exptrack/sessions — Session Trees: opt-in tree-shaped tracking of exploratory work.

Core entry points:
    SessionManager        — create/end sessions, add nodes, promote experiments
    get_current_session   — module-level reference to the active SessionManager
    set_current_session   — installs/clears the active SessionManager
"""
from __future__ import annotations

from .manager import SessionManager, get_current_session, set_current_session
from .tree import render_ascii, render_json

__all__ = [
    "SessionManager",
    "get_current_session",
    "set_current_session",
    "render_ascii",
    "render_json",
]
