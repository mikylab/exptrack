"""
exptrack/dashboard/static_parts/scripts.py — JavaScript re-exports

All JS sections are now in static_parts/js/ as individual modules.
This file re-exports them for backward compatibility. Keep the list in sync
with static_parts/js/__init__.py so the shim exposes every module.
"""

from .js import (
    JS_CHARTS,
    JS_COMMANDS,
    JS_COMPARE,
    JS_CONFUSION,
    JS_CORE,
    JS_DETAIL,
    JS_EXPERIMENTS,
    JS_HIGHLIGHT,
    JS_IMAGE_COMPARE,
    JS_INIT,
    JS_INLINE_EDIT,
    JS_MANUAL,
    JS_MUTATIONS,
    JS_OWL,
    JS_SESSIONS,
    JS_SIDEBAR,
    JS_STAGE,
    JS_STUDIES,
    JS_TABLE,
    JS_TIMELINE,
    JS_TODOS,
    JS_TRASH,
    get_all_js,
)

__all__ = [
    "JS_CHARTS",
    "JS_COMMANDS",
    "JS_COMPARE",
    "JS_CONFUSION",
    "JS_CORE",
    "JS_DETAIL",
    "JS_EXPERIMENTS",
    "JS_HIGHLIGHT",
    "JS_IMAGE_COMPARE",
    "JS_INIT",
    "JS_INLINE_EDIT",
    "JS_MANUAL",
    "JS_MUTATIONS",
    "JS_OWL",
    "JS_SESSIONS",
    "JS_SIDEBAR",
    "JS_STAGE",
    "JS_STUDIES",
    "JS_TABLE",
    "JS_TIMELINE",
    "JS_TODOS",
    "JS_TRASH",
    "get_all_js",
]
