# Contributing to expTrack

Thanks for your interest in contributing to expTrack!

## Development Setup

```bash
git clone https://github.com/mikylab/expTrack.git
cd expTrack
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
```

## Code Style

- **stdlib only** — no external dependencies. Every import must come from the Python standard library.
- Keep functions focused (~40 lines max). Split if larger.
- Reuse existing utilities from `core/db.py`, `config.py`, and `cli/formatting.py` before writing new helpers.
- Wrap external operations (file I/O, git, plugin calls) in try/except. Never let a capture failure crash the user's training script.
- Use `from __future__ import annotations` at the top of every module.

## Dashboard Changes

- Keep existing JS function signatures stable — other modules may call them.
- Use `api()` / `postApi()` helpers for API calls.
- Use CSS custom properties from `:root` instead of hardcoded colors.
- Follow the inline-editing pattern (double-click to edit, Enter/Escape to save/cancel).

## Pull Requests

1. Fork the repo and create a feature branch from `main`.
2. Make your changes. Add tests if applicable.
3. Run `pytest tests/ -v` and ensure all tests pass.
4. Submit a pull request with a clear description of what changed and why.

## Reporting Issues

Open an issue at https://github.com/mikylab/expTrack/issues with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Python version and OS
