"""
exptrack/dashboard/static_parts/js/ — Modular JavaScript sections

Each module contains one JS section as a string constant.
The get_all_js() function assembles them in the correct order.
"""

from .core import JS_CORE
from .owl import JS_OWL
from .sidebar import JS_SIDEBAR
from .table import JS_TABLE
from .experiments import JS_EXPERIMENTS
from .inline_edit import JS_INLINE_EDIT
from .detail import JS_DETAIL
from .compare import JS_COMPARE
from .mutations import JS_MUTATIONS
from .timeline import JS_TIMELINE
from .image_compare import JS_IMAGE_COMPARE
from .init import JS_INIT
from .studies import JS_STUDIES
from .stage import JS_STAGE
from .manual import JS_MANUAL


def get_all_js() -> str:
    """Concatenate all JavaScript sections in the correct order."""
    return (JS_CORE + JS_OWL + JS_SIDEBAR + JS_TABLE +
            JS_EXPERIMENTS + JS_INLINE_EDIT + JS_DETAIL +
            JS_COMPARE + JS_MUTATIONS + JS_TIMELINE +
            JS_IMAGE_COMPARE + JS_STUDIES + JS_STAGE + JS_MANUAL + JS_INIT)


__all__ = [
    "JS_CORE", "JS_OWL", "JS_SIDEBAR", "JS_TABLE",
    "JS_EXPERIMENTS", "JS_INLINE_EDIT", "JS_DETAIL",
    "JS_COMPARE", "JS_MUTATIONS", "JS_TIMELINE",
    "JS_IMAGE_COMPARE", "JS_INIT", "JS_STUDIES",
    "JS_STAGE", "JS_MANUAL", "get_all_js",
]
