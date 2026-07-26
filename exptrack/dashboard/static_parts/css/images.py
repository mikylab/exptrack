"""Loader shim: content extracted to exptrack/dashboard/static/css/."""
from .._loader import _load_css as _load

CSS_IMAGES = _load('images.css')
CSS_IMAGE_COMPARE = _load('image_compare.css')
