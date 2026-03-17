"""
exptrack/dashboard/static_parts/scripts.py — JavaScript re-exports

All JS sections are now in static_parts/js/ as individual modules.
This file re-exports them for backward compatibility.
"""

from .js import (
    JS_CORE, JS_OWL, JS_SIDEBAR, JS_TABLE,
    JS_EXPERIMENTS, JS_INLINE_EDIT, JS_DETAIL,
    JS_COMPARE, JS_MUTATIONS, JS_TIMELINE,
    JS_IMAGE_COMPARE, JS_INIT, JS_STUDIES,
    JS_STAGE, JS_MANUAL, get_all_js,
)

__all__ = [
    "JS_CORE", "JS_OWL", "JS_SIDEBAR", "JS_TABLE",
    "JS_EXPERIMENTS", "JS_INLINE_EDIT", "JS_DETAIL",
    "JS_COMPARE", "JS_MUTATIONS", "JS_TIMELINE",
    "JS_IMAGE_COMPARE", "JS_INIT", "JS_STUDIES",
    "JS_STAGE", "JS_MANUAL", "get_all_js",
]
