"""
exptrack/dashboard/js/ — JavaScript module convenience re-exports

JS sections live in dashboard/static_parts/js/ as individual modules.
This package provides convenient aliased access for testing and external use.

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
  - image_compare: Image diff viewer
  - studies: Study management
  - stage: Stage/pipeline state tracking
  - manual: Manual experiment creation
  - init: Initialization and event binding
"""

from ..static_parts.js import (
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
    JS_IMAGE_COMPARE as image_compare,
    JS_STUDIES as studies,
    JS_STAGE as stage,
    JS_MANUAL as manual,
    JS_INIT as init,
    get_all_js,
)

__all__ = [
    "core", "owl", "sidebar", "table", "experiments",
    "inline_edit", "detail", "compare", "mutations",
    "timeline", "image_compare", "studies", "stage",
    "manual", "init", "get_all_js",
]
