"""
exptrack/dashboard/static_parts/scripts.py — JavaScript re-exports

All JS sections are now in static_parts/js/ as individual modules.
This file re-exports them for backward compatibility.
"""

from .js import (
    JS_COMPARE,
    JS_CORE,
    JS_DETAIL,
    JS_EXPERIMENTS,
    JS_IMAGE_COMPARE,
    JS_INIT,
    JS_INLINE_EDIT,
    JS_MANUAL,
    JS_MUTATIONS,
    JS_OWL,
    JS_SIDEBAR,
    JS_STAGE,
    JS_STUDIES,
    JS_TABLE,
    JS_TIMELINE,
    get_all_js,
)

__all__ = [
    "JS_COMPARE",
    "JS_CORE",
    "JS_DETAIL",
    "JS_EXPERIMENTS",
    "JS_IMAGE_COMPARE",
    "JS_INIT",
    "JS_INLINE_EDIT",
    "JS_MANUAL",
    "JS_MUTATIONS",
    "JS_OWL",
    "JS_SIDEBAR",
    "JS_STAGE",
    "JS_STUDIES",
    "JS_TABLE",
    "JS_TIMELINE",
    "get_all_js",
]
