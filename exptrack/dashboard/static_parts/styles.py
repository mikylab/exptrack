"""
exptrack/dashboard/static_parts/styles.py — CSS style re-exports

All CSS sections are now in static_parts/css/ as individual modules.
This file re-exports them for backward compatibility.
"""

from .css import (
    CSS_CARDS,
    CSS_CODE,
    CSS_COMPARE,
    CSS_COMPONENTS,
    CSS_DETAIL,
    CSS_IMAGE_COMPARE,
    CSS_IMAGES,
    CSS_LAYOUT,
    CSS_RESET,
    CSS_STUDIES,
    CSS_TABLE,
    CSS_TIMELINE,
    get_all_css,
)

__all__ = [
    "CSS_CARDS",
    "CSS_CODE",
    "CSS_COMPARE",
    "CSS_COMPONENTS",
    "CSS_DETAIL",
    "CSS_IMAGES",
    "CSS_IMAGE_COMPARE",
    "CSS_LAYOUT",
    "CSS_RESET",
    "CSS_STUDIES",
    "CSS_TABLE",
    "CSS_TIMELINE",
    "get_all_css",
]
