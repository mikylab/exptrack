"""Loader shim: content extracted to exptrack/dashboard/static/css/."""
from .._loader import _load_css as _load

CSS_COMPONENTS = _load('components.css')
