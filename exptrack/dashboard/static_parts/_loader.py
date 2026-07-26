"""File loaders for the extracted dashboard JS/CSS assets.

The dashboard JS/CSS used to live as big Python string constants; the content
now lives in exptrack/dashboard/static/{js,css}/*. Each per-section module
(e.g. js/core.py) is a thin shim that loads its file through here, preserving
every JS_*/CSS_* name so imports and get_all_js()/get_all_css() are unchanged.
"""
from functools import lru_cache
from pathlib import Path

# _loader.py lives in static_parts/; the assets live in the sibling static/.
_STATIC = Path(__file__).resolve().parent.parent / "static"


@lru_cache(maxsize=None)
def _load_js(name: str) -> str:
    return (_STATIC / "js" / name).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def _load_css(name: str) -> str:
    return (_STATIC / "css" / name).read_text(encoding="utf-8")
