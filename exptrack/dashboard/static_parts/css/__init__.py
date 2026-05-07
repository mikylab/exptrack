"""
exptrack/dashboard/static_parts/css/ — Modular CSS styles

Each module contains one or more related CSS sections as string constants.
The get_all_css() function assembles them in the correct order.
"""

from .cards import CSS_CARDS
from .charts import CSS_CHARTS
from .code import CSS_CODE
from .compare import CSS_COMPARE
from .components import CSS_COMPONENTS
from .detail import CSS_DETAIL
from .images import CSS_IMAGE_COMPARE, CSS_IMAGES
from .layout import CSS_LAYOUT
from .reset import CSS_RESET
from .sessions import CSS_SESSIONS
from .studies import CSS_STUDIES
from .table import CSS_TABLE
from .timeline import CSS_TIMELINE
from .toolbox import CSS_TOOLBOX


def get_all_css() -> str:
    """Concatenate all CSS sections in the correct order."""
    return (CSS_RESET + CSS_LAYOUT + CSS_CARDS + CSS_TABLE +
            CSS_DETAIL + CSS_CHARTS + CSS_CODE + CSS_TIMELINE + CSS_COMPARE +
            CSS_COMPONENTS + CSS_STUDIES + CSS_IMAGES + CSS_IMAGE_COMPARE +
            CSS_TOOLBOX + CSS_SESSIONS)


__all__ = [
    "CSS_CARDS",
    "CSS_CHARTS",
    "CSS_CODE",
    "CSS_COMPARE",
    "CSS_COMPONENTS",
    "CSS_DETAIL",
    "CSS_IMAGES",
    "CSS_IMAGE_COMPARE",
    "CSS_LAYOUT",
    "CSS_RESET",
    "CSS_SESSIONS",
    "CSS_STUDIES",
    "CSS_TABLE",
    "CSS_TIMELINE",
    "CSS_TOOLBOX",
    "get_all_css",
]
