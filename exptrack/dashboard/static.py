"""
exptrack/dashboard/static.py — Dashboard HTML/CSS/JS (single-page app)

Assembles DASHBOARD_HTML from modular parts in static_parts/.
"""
from .static_parts.styles import get_all_css
from .static_parts.html import HTML_HEAD, HTML_BODY, HTML_FOOTER
from .static_parts.scripts import get_all_js

DASHBOARD_HTML = HTML_HEAD + get_all_css() + HTML_BODY + get_all_js() + HTML_FOOTER
