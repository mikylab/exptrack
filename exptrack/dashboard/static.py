"""
exptrack/dashboard/static.py — Dashboard HTML/CSS/JS (single-page app)

Assembles DASHBOARD_HTML from modular parts in static_parts/. The CSS and JS
bundles are served as separate `/static/dashboard.css` and
`/static/dashboard.js` responses (referenced from the HTML via
hash-versioned `<link>` / `<script src>`), so the browser caches the large
JS/CSS across page reloads instead of re-parsing them inline every time. The
`?v=<hash>` query busts that cache automatically whenever the content
changes, so a stale bundle can never be served.
"""
import hashlib

from .static_parts.html import HTML_BODY, HTML_FOOTER, HTML_HEAD
from .static_parts.scripts import get_all_js
from .static_parts.styles import get_all_css

# Assembled bundles + content hashes for cache-busting. Built once at import.
DASHBOARD_CSS = get_all_css()
DASHBOARD_JS = get_all_js()
_CSS_HASH = hashlib.sha256(DASHBOARD_CSS.encode("utf-8")).hexdigest()[:12]
_JS_HASH = hashlib.sha256(DASHBOARD_JS.encode("utf-8")).hexdigest()[:12]

CSS_URL = f"/static/dashboard.css?v={_CSS_HASH}"
JS_URL = f"/static/dashboard.js?v={_JS_HASH}"


def _assemble_html() -> str:
    """Build the page shell with external <link>/<script src> references.

    The three HTML constants wrap the inline asset slots as
    ``…<style>`` / ``</style>…</head>…<script>`` / ``</script>…``; swap those
    inline wrappers for external references (localized here so html.py's body
    stays untouched). The boundary tokens are asserted so a future html.py
    edit that moves them fails loudly instead of silently inlining nothing.
    """
    assert HTML_HEAD.endswith("<style>\n"), "HTML_HEAD must end with the <style> slot"
    assert HTML_BODY.startswith("</style>\n"), "HTML_BODY must open with </style>"
    assert HTML_BODY.endswith("<script>\n"), "HTML_BODY must end with the <script> slot"
    assert HTML_FOOTER.startswith("</script>\n"), "HTML_FOOTER must open with </script>"

    head = HTML_HEAD[: -len("<style>\n")] + f'<link rel="stylesheet" href="{CSS_URL}">\n'
    body = HTML_BODY[len("</style>\n"):-len("<script>\n")] + f'<script src="{JS_URL}"></script>\n'
    footer = HTML_FOOTER[len("</script>\n"):]
    return head + body + footer


DASHBOARD_HTML = _assemble_html()
