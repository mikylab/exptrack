"""
exptrack/dashboard/js/ — JavaScript module organization

The JS sections are still defined in dashboard/static_parts/scripts.py
as named string constants. This package provides convenient access to
individual sections for testing and future modularization.

Sections:
  - core: State variables, API helpers, dark mode, filter bar
  - owl: Mascot animation and speech bubble
  - sidebar: Sidebar actions, bulk operations
  - table: Table rendering, sorting, filtering
  - experiments: Experiment list rendering
  - inline_edit: Double-click inline editing
  - detail: Experiment detail panel, tabs
  - compare: Compare view logic
  - mutations: Tag/note/name mutation helpers
  - timeline: Timeline rendering, cell source viewer
  - studies: Study management
  - init: Initialization and event binding
"""

from ..static_parts.scripts import (
    JS_CORE as core,
    JS_OWL as owl,
    JS_SIDEBAR as sidebar,
    JS_TABLE as table,
    JS_EXPERIMENTS as experiments,
    JS_INLINE_EDIT as inline_edit,
    JS_DETAIL as detail,
    JS_COMPARE as compare,
    JS_MUTATIONS as mutations,
    JS_TIMELINE as timeline,
    JS_STUDIES as studies,
    JS_INIT as init,
    get_all_js,
)

__all__ = [
    "core", "owl", "sidebar", "table", "experiments",
    "inline_edit", "detail", "compare", "mutations",
    "timeline", "studies", "init", "get_all_js",
]
