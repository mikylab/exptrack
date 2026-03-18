"""
exptrack/dashboard/js/ — JavaScript module convenience re-exports

JS sections live in dashboard/static_parts/js/ as individual modules.
This package provides convenient aliased access for testing and external use.

Sections:
  - core: State variables, API helpers, dark mode, filter bar
  - charts_tab: Metric chart selector, scale controls, Chart.js rendering
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
    JS_CHARTS as charts_tab,
)
from ..static_parts.js import (
    JS_COMPARE as compare,
)
from ..static_parts.js import (
    JS_CORE as core,
)
from ..static_parts.js import (
    JS_DETAIL as detail,
)
from ..static_parts.js import (
    JS_EXPERIMENTS as experiments,
)
from ..static_parts.js import (
    JS_IMAGE_COMPARE as image_compare,
)
from ..static_parts.js import (
    JS_INIT as init,
)
from ..static_parts.js import (
    JS_INLINE_EDIT as inline_edit,
)
from ..static_parts.js import (
    JS_MANUAL as manual,
)
from ..static_parts.js import (
    JS_MUTATIONS as mutations,
)
from ..static_parts.js import (
    JS_OWL as owl,
)
from ..static_parts.js import (
    JS_SIDEBAR as sidebar,
)
from ..static_parts.js import (
    JS_STAGE as stage,
)
from ..static_parts.js import (
    JS_STUDIES as studies,
)
from ..static_parts.js import (
    JS_TABLE as table,
)
from ..static_parts.js import (
    JS_TIMELINE as timeline,
)
from ..static_parts.js import (
    get_all_js,
)

__all__ = [
    "charts_tab",
    "compare",
    "core",
    "detail",
    "experiments",
    "get_all_js",
    "image_compare",
    "init",
    "inline_edit",
    "manual",
    "mutations",
    "owl",
    "sidebar",
    "stage",
    "studies",
    "table",
    "timeline",
]
