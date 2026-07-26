"""
exptrack/dashboard/routes/write_routes/_shared.py — helpers shared by the
mutation endpoints.
"""
from __future__ import annotations


def body_str(body: dict, key: str, default: str = "") -> str:
    """Read a request-body field as a stripped string.

    Every endpoint here was written against the dashboard's own JS, which
    sends form fields as strings, so they all did
    ``body.get("value", "").strip()`` directly. Any other client sending
    correct JSON types — ``{"value": 0.8}`` rather than ``{"value": "0.8"}``
    — hit ``.strip()`` on a float and raised AttributeError. That propagated
    out of the route and killed the connection with no response at all, so
    the caller saw a dropped socket rather than an error it could read.

    Coercing here keeps the string-in behaviour identical (``str`` of a str
    is the same str) while making a JSON number, bool, or null a well-formed
    input instead of a crash. ``None`` maps to the default, since a JSON
    ``null`` means "absent", not the literal "None".
    """
    value = body.get(key, default)
    if value is None:
        return default
    return value.strip() if isinstance(value, str) else str(value).strip()
