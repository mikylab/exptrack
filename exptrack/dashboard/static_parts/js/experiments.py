"""Loader shim: content extracted to exptrack/dashboard/static/js/."""
from .._loader import _load_js as _load

JS_EXPERIMENTS = _load('experiments.js')
