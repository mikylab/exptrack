"""
exptrack/dashboard/static_parts/js/ — Modular JavaScript sections

Each module contains one JS section as a string constant.
The get_all_js() function assembles them in the correct order.
"""

from .charts import JS_CHARTS
from .compare import JS_COMPARE
from .core import JS_CORE
from .detail import JS_DETAIL
from .experiments import JS_EXPERIMENTS
from .image_compare import JS_IMAGE_COMPARE
from .init import JS_INIT
from .inline_edit import JS_INLINE_EDIT
from .manual import JS_MANUAL
from .mutations import JS_MUTATIONS
from .owl import JS_OWL
from .sidebar import JS_SIDEBAR
from .stage import JS_STAGE
from .studies import JS_STUDIES
from .table import JS_TABLE
from .timeline import JS_TIMELINE
from .todos import JS_TODOS
from .commands import JS_COMMANDS
from .confusion import JS_CONFUSION


def get_all_js() -> str:
    """Concatenate all JavaScript sections in the correct order."""
    return (JS_CORE + JS_OWL + JS_SIDEBAR + JS_TABLE +
            JS_EXPERIMENTS + JS_INLINE_EDIT + JS_DETAIL + JS_CHARTS +
            JS_COMPARE + JS_MUTATIONS + JS_TIMELINE +
            JS_IMAGE_COMPARE + JS_STUDIES + JS_STAGE + JS_MANUAL +
            JS_TODOS + JS_COMMANDS + JS_CONFUSION + JS_INIT)


__all__ = [
    "JS_CHARTS",
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
    "JS_TODOS",
    "JS_COMMANDS",
    "JS_CONFUSION",
    "get_all_js",
]
