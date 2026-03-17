# Contributing

Contributions are welcome! Here's how to get started:

1. Fork the repository and clone your fork
2. Create a virtual environment and install in development mode:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```
3. Create a branch for your change (`git checkout -b my-feature`)
4. Make your changes -- remember, **stdlib only** (no external dependencies)
5. Run `ruff check exptrack/ tests/` and fix any issues
6. Commit and push to your fork
7. Open a pull request against `main`

## Guidelines

- **No external dependencies.** Every import must come from the Python standard library.
- **Keep functions focused.** If a function exceeds ~40 lines, consider splitting it.
- **Error boundaries.** Wrap external operations (file I/O, git, plugin calls) in try/except. Never let a capture failure crash the user's training script.
- **Dashboard changes.** Keep existing JS function signatures stable. Use `api()` / `postApi()` helpers for API calls. Follow the inline-editing pattern for new UI features.

## Development Setup

```bash
git clone https://github.com/mikylab/expTrack.git
cd expTrack
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs exptrack in editable mode along with dev tools (pytest, ruff).

## Linting

expTrack uses [ruff](https://docs.astral.sh/ruff/) for linting and import sorting:

```bash
ruff check exptrack/ tests/        # check for issues
ruff check exptrack/ tests/ --fix  # auto-fix what's possible
```

Ruff configuration is in `pyproject.toml` under `[tool.ruff]`.

## Type Checking

The package ships a `py.typed` marker (PEP 561), so type checkers like mypy and pyright will pick up the inline annotations:

```bash
# optional -- not required for development
pip install mypy
mypy exptrack/
```

Type annotations use `from __future__ import annotations` throughout, so modern syntax (`str | None`, `dict[str, Any]`) works on Python 3.8+.

## Tests

```bash
pytest                             # run all tests
pytest tests/test_experiment.py    # run a specific test file
```
