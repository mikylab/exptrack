"""Loader shim: content extracted to exptrack/dashboard/static/css/."""
from .._loader import _load_css as _load

CSS_RESET = _load('reset.css')
