"""
exptrack/dashboard/static_parts/css/ — Modular CSS styles

Each module contains one or more related CSS sections as string constants.
The get_all_css() function assembles them in the correct order.
"""

from .reset import CSS_RESET
from .layout import CSS_LAYOUT
from .cards import CSS_CARDS
from .table import CSS_TABLE
from .detail import CSS_DETAIL
from .code import CSS_CODE
from .timeline import CSS_TIMELINE
from .compare import CSS_COMPARE
from .components import CSS_COMPONENTS
from .studies import CSS_STUDIES
from .images import CSS_IMAGES, CSS_IMAGE_COMPARE


def get_all_css() -> str:
    """Concatenate all CSS sections in the correct order."""
    return (CSS_RESET + CSS_LAYOUT + CSS_CARDS + CSS_TABLE +
            CSS_DETAIL + CSS_CODE + CSS_TIMELINE + CSS_COMPARE +
            CSS_COMPONENTS + CSS_STUDIES + CSS_IMAGES + CSS_IMAGE_COMPARE)


__all__ = [
    "CSS_RESET", "CSS_LAYOUT", "CSS_CARDS", "CSS_TABLE",
    "CSS_DETAIL", "CSS_CODE", "CSS_TIMELINE", "CSS_COMPARE",
    "CSS_COMPONENTS", "CSS_STUDIES", "CSS_IMAGES", "CSS_IMAGE_COMPARE",
    "get_all_css",
]
