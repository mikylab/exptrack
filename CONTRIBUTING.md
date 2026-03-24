# Contributing to expTrack

Thanks for your interest in contributing!

## Setup

```bash
git clone https://github.com/mikylab/expTrack.git
cd expTrack
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Code Style

- **stdlib only** — every import must come from the Python standard library
- Keep functions focused (~40 lines max)
- Reuse existing utilities (`core/db.py`, `config.py`, `cli/formatting.py`) before writing new helpers
- Wrap external operations in try/except — never crash the user's script
- Use `from __future__ import annotations` at the top of every module

## Dashboard Changes

- Keep existing JS function signatures stable
- Use `api()` / `postApi()` helpers for API calls
- Use CSS custom properties from `:root` instead of hardcoded colors
- Follow the inline-editing pattern (double-click to edit, Enter/Escape to save/cancel)

## Testing & Linting

```bash
pytest tests/ -v                       # run tests
ruff check exptrack/ tests/            # lint
ruff check exptrack/ tests/ --fix      # auto-fix
```

## Pull Requests

1. Fork the repo, create a feature branch from `main`
2. Make changes, add tests if applicable
3. Ensure `pytest` and `ruff check` pass
4. Submit a PR with a clear description of what and why

## Reporting Issues

Open an issue at https://github.com/mikylab/expTrack/issues with:
- What you expected vs. what happened
- Steps to reproduce
- Python version and OS
