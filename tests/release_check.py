#!/usr/bin/env python
"""Pre-release consistency check — run before tagging a release.

Catches the release footguns that a green test suite does NOT catch:

  1. The version in pyproject.toml has a matching CHANGELOG.md entry.
  2. Every dashboard static asset (.js/.css/.svg) is covered by a
     package-data glob. If a new JS file isn't, the tests still pass (they
     import the source), but the *published wheel* ships without it and the
     dashboard breaks for everyone who `pip install`s it. This is the single
     most likely way to ship a broken release.
  3. If the `build` module is available, actually build a wheel and confirm
     the static files are inside it. Skipped (not failed) if build is absent.

stdlib only. Run with `python tests/release_check.py`.
"""
import fnmatch
import functools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@functools.lru_cache(maxsize=1)
def _pyproject_text():
    return (ROOT / "pyproject.toml").read_text()


def read_version():
    text = _pyproject_text()
    try:
        import tomllib  # 3.11+
        return tomllib.loads(text)["project"]["version"]
    except ModuleNotFoundError:
        # 3.9 / 3.10 fallback: pull it out by hand.
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("version") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("release-check: could not read version from pyproject.toml")


def declared_globs():
    """Parse [tool.setuptools.package-data] into {package: [globs]}."""
    text = _pyproject_text()
    try:
        import tomllib
        return tomllib.loads(text)["tool"]["setuptools"]["package-data"]
    except ModuleNotFoundError:
        # Minimal hand-parse for 3.9/3.10: good enough for our flat table.
        import re
        out, in_section = {}, False
        for line in text.splitlines():
            s = line.strip()
            if s == "[tool.setuptools.package-data]":
                in_section = True
                continue
            if in_section:
                if s.startswith("["):
                    break
                m = re.match(r'"?([\w.]+)"?\s*=\s*\[(.*)\]', s)
                if m:
                    pkg = m.group(1)
                    globs = re.findall(r'"([^"]+)"', m.group(2))
                    out[pkg] = globs
        return out


def check_changelog(version):
    text = (ROOT / "CHANGELOG.md").read_text()
    if version in text:
        print(f"  ok: CHANGELOG.md mentions version {version}")
        return []
    return [f"CHANGELOG.md has no entry for version {version}"]


def check_static_coverage():
    """Every static asset must match at least one package-data glob."""
    globs = declared_globs()
    problems = []
    static_root = ROOT / "exptrack" / "dashboard" / "static"
    vendor = ROOT / "exptrack" / "dashboard" / "vendor"
    assets = list(static_root.rglob("*.js")) + list(static_root.rglob("*.css")) \
        + list(static_root.rglob("*.svg")) + list(vendor.rglob("*.js"))
    for asset in assets:
        # Find the package directory that declares a matching package-data glob.
        matched = False
        for pkg, patterns in globs.items():
            base = ROOT / Path(*pkg.split("."))
            try:
                rel = asset.relative_to(base).as_posix()
            except ValueError:
                continue
            if any(fnmatch.fnmatch(rel, pat) for pat in patterns):
                matched = True
                break
        if not matched:
            rel = asset.relative_to(ROOT).as_posix()
            problems.append(f"static asset not covered by package-data: {rel}")
    if not problems:
        print(f"  ok: all {len(assets)} dashboard static assets are covered by package-data")
    return problems


def check_examples_coverage():
    """Bundled examples must ship in the wheel. `.py` is collected automatically,
    but `.sh` only ships if a package-data glob names it — guard that."""
    globs = declared_globs()
    ex_dir = ROOT / "exptrack" / "examples"
    if not ex_dir.exists():
        return []
    patterns = globs.get("exptrack.examples", [])
    problems = []
    for asset in ex_dir.iterdir():
        if not asset.is_file():
            continue  # __pycache__ and other dirs
        if asset.suffix == ".py":
            continue  # collected by packages.find
        rel = asset.name
        if not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            problems.append(f"bundled example not covered by package-data: examples/{rel}")
    if not problems:
        print("  ok: bundled examples are covered by package-data")
    return problems


def check_wheel(version):
    try:
        import build  # noqa: F401
    except ModuleNotFoundError:
        print("  skip: `build` not installed — skipping real wheel inspection "
              "(pip install build to enable)")
        return []
    import subprocess
    import tempfile
    import zipfile
    with tempfile.TemporaryDirectory() as out:
        r = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", out],
            cwd=ROOT, capture_output=True, text=True,
        )
        if r.returncode != 0:
            return ["wheel build failed:\n" + r.stdout + r.stderr]
        wheels = list(Path(out).glob("*.whl"))
        if not wheels:
            return ["wheel build produced no .whl"]
        names = zipfile.ZipFile(wheels[0]).namelist()
        js = [n for n in names if n.endswith(".js")]
        css = [n for n in names if n.endswith(".css")]
        if not js or not css:
            return [f"built wheel is missing static assets (js={len(js)}, css={len(css)})"]
        print(f"  ok: built wheel contains {len(js)} JS and {len(css)} CSS files")
    return []


def main():
    version = read_version()
    print(f"exptrack release-check — version {version}")
    problems = []
    problems += check_changelog(version)
    problems += check_static_coverage()
    problems += check_examples_coverage()
    problems += check_wheel(version)
    if problems:
        print("\nRELEASE-CHECK FAILED:")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)
    print("\nRELEASE-CHECK PASSED — safe to tag and publish.")


if __name__ == "__main__":
    main()
