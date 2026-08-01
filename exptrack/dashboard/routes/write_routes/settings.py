"""
exptrack/dashboard/routes/write_routes/settings.py

Config-backed dashboard settings: timezone, metric display, capture,
and result types.
"""
from __future__ import annotations

from ._shared import body_str


def api_set_timezone(body: dict) -> dict:
    from exptrack.config import load, save
    tz = body_str(body, "timezone")
    valid = {
        "", "UTC", "America/New_York", "America/Chicago", "America/Denver",
        "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Europe/Paris",
        "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata", "Australia/Sydney",
    }
    if tz not in valid:
        return {"error": "invalid timezone"}
    conf = load()
    conf["timezone"] = tz
    save(conf)
    return {"ok": True, "timezone": tz}


def api_set_metric_settings(body: dict) -> dict:
    from exptrack.config import load, reload, save
    conf = load()
    keep_every = body.get("metric_keep_every")
    max_points = body.get("metric_max_points")
    if keep_every is not None:
        try:
            val = max(1, int(keep_every))
            conf["metric_keep_every"] = val
        except (ValueError, TypeError, OverflowError):
            return {"error": "metric_keep_every must be a positive integer"}
    if max_points is not None:
        try:
            val = max(10, min(50000, int(max_points)))
            conf["metric_max_points"] = val
        except (ValueError, TypeError, OverflowError):
            return {"error": "metric_max_points must be an integer (10-50000)"}
    save(conf)
    reload()
    return {"ok": True, "metric_keep_every": conf.get("metric_keep_every", 1),
            "metric_max_points": conf.get("metric_max_points", 500)}


def api_set_capture_settings(body: dict) -> dict:
    from exptrack.config import load, reload, save
    conf = load()
    notebook_capture = body.get("notebook_capture")
    max_mb = body.get("var_fingerprint_max_mb")
    if notebook_capture is not None:
        auto = dict(conf.get("auto_capture", {}) or {})
        auto["notebook"] = bool(notebook_capture)
        conf["auto_capture"] = auto
    if max_mb is not None:
        try:
            val = max(1, min(10000, int(max_mb)))
            conf["var_fingerprint_max_mb"] = val
        except (ValueError, TypeError):
            return {"error": "var_fingerprint_max_mb must be an integer (1-10000)"}
    save(conf)
    reload()
    auto = conf.get("auto_capture", {}) or {}
    return {"ok": True,
            "notebook_capture": bool(auto.get("notebook", True)),
            "var_fingerprint_max_mb": int(conf.get("var_fingerprint_max_mb", 100))}


def api_manage_result_types(body: dict) -> dict:
    """Add/remove result types or namespace prefixes from project config."""
    from exptrack.config import load, reload, save
    conf = load()
    default_types = ["accuracy", "loss", "auroc", "f1", "precision", "recall",
                     "mse", "mae", "r2", "perplexity", "bleu"]
    default_prefixes = ["train", "val", "test"]
    types = list(conf.get("result_types", default_types))
    prefixes = list(conf.get("metric_prefixes", default_prefixes))

    target = body.get("target", "type")  # "type" or "prefix"
    action = body.get("action", "")

    if target == "prefix":
        if action == "add":
            name = body_str(body, "name").lower().rstrip("/")
            if not name:
                return {"error": "empty name"}
            if name not in prefixes:
                prefixes.append(name)
        elif action == "remove":
            index = body.get("index", -1)
            if 0 <= index < len(prefixes):
                prefixes.pop(index)
        else:
            return {"error": "invalid action"}
        conf["metric_prefixes"] = prefixes
    else:
        if action == "add":
            name = body_str(body, "name").lower()
            if not name:
                return {"error": "empty name"}
            if name not in types:
                types.append(name)
        elif action == "remove":
            index = body.get("index", -1)
            if 0 <= index < len(types):
                types.pop(index)
        else:
            return {"error": "invalid action"}
        conf["result_types"] = types

    save(conf)
    reload()
    return {"ok": True, "types": types, "prefixes": prefixes}
