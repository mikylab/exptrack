"""
exptrack/dashboard/static_parts/styles.py — CSS style re-exports

All CSS sections are now in static_parts/css/ as individual modules.
This file re-exports them for backward compatibility.
"""

from .css import (
    CSS_RESET, CSS_LAYOUT, CSS_CARDS, CSS_TABLE,
    CSS_DETAIL, CSS_CODE, CSS_TIMELINE, CSS_COMPARE,
    CSS_COMPONENTS, CSS_STUDIES, CSS_IMAGES, CSS_IMAGE_COMPARE,
    get_all_css,
)

__all__ = [
    "CSS_RESET", "CSS_LAYOUT", "CSS_CARDS", "CSS_TABLE",
    "CSS_DETAIL", "CSS_CODE", "CSS_TIMELINE", "CSS_COMPARE",
    "CSS_COMPONENTS", "CSS_STUDIES", "CSS_IMAGES", "CSS_IMAGE_COMPARE",
    "get_all_css",
]
