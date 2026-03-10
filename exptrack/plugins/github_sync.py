"""
exptrack/plugins/github_sync.py

Appends a single JSON line to a file in your GitHub repo when a run finishes.
Metadata only — never large files. The file becomes a searchable run log.

Config in .exptrack/config.json:
    {
      "plugins": {
        "enabled": ["github_sync"],
        "github_sync": {
          "repo":      "yourname/NewCode1",
          "file":      "experiment_log/runs.jsonl",
          "branch":    "main",
          "token_env": "GITHUB_TOKEN"
        }
      }
    }

PAT scopes needed: repo > Contents (read + write)
"""
from __future__ import annotations
import base64
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

from . import Plugin

if TYPE_CHECKING:
    from ..core import Experiment


class GitHubSyncPlugin(Plugin):
    name = "github_sync"

    def __init__(self, config: dict):
        self.repo      = config.get("repo", "")
        self.file      = config.get("file", "experiment_log/runs.jsonl")
        self.branch    = config.get("branch", "main")
        self.token_env = config.get("token_env", "GITHUB_TOKEN")
        if not self.repo:
            print("[exptrack] github_sync: set plugins.github_sync.repo in config.json")

    def on_finish(self, exp: "Experiment"):
        self._push(exp)

    def on_fail(self, exp: "Experiment", error: str):
        self._push(exp)

    def _push(self, exp: "Experiment"):
        if not self.repo:
            return
        tok = os.environ.get(self.token_env, "")
        if not tok:
            print(f"[exptrack] github_sync: ${self.token_env} not set — skipping sync")
            return

        record = {
            "id":         exp.id,
            "name":       exp.name,
            "status":     exp.status,
            "project":    exp.project,
            "created_at": exp.created_at,
            "duration_s": round(exp.duration_s or 0, 2),
            "script":     Path(exp.script).name if exp.script else "",
            "git_branch": exp.git_branch,
            "git_commit": exp.git_commit,
            "diff_lines": len((exp.git_diff or "").splitlines()),
            "params":     exp._params,
            "metrics":    exp.last_metrics(),
            "tags":       exp.tags,
            "notes":      exp.notes,
        }

        try:
            current, sha = self._get_file(tok)
            new_content = (current.rstrip("\n") + "\n" if current else "") + \
                          json.dumps(record, default=str) + "\n"
            self._put_file(tok, new_content, sha,
                           msg=f"exptrack: {exp.status} {exp.name[:50]} [{exp.id[:6]}]")
            print(f"[exptrack] Synced to {self.repo}/{self.file}")
        except Exception as e:
            print(f"[exptrack] github_sync failed: {e}")

    def _api(self, method: str, path: str, body: dict, tok: str) -> dict:
        url = f"https://api.github.com/{path.lstrip('/')}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body else None,
            method=method,
            headers={
                "Authorization": f"Bearer {tok}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    def _get_file(self, tok: str) -> tuple[str, str | None]:
        try:
            resp = self._api("GET",
                f"repos/{self.repo}/contents/{self.file}?ref={self.branch}",
                body=None, tok=tok)
            return base64.b64decode(resp["content"]).decode(), resp["sha"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "", None
            raise

    def _put_file(self, tok: str, content: str, sha: str | None, msg: str):
        body = {
            "message": msg,
            "content": base64.b64encode(content.encode()).decode(),
            "branch":  self.branch,
        }
        if sha:
            body["sha"] = sha
        self._api("PUT", f"repos/{self.repo}/contents/{self.file}", body, tok)


plugin_class = GitHubSyncPlugin
