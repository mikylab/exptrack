# Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) in the project root for full guidelines.

## Quick Setup

```bash
git clone https://github.com/mikylab/expTfrack.git
cd exptrack
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Key Rules

- **stdlib only** — no external dependencies
- **Keep functions focused** — ~40 lines max
- **Error boundaries** — never let capture failures crash the user's script
- **Dashboard changes** — keep JS function signatures stable, use `api()`/`postApi()` helpers, use CSS custom properties

## Workflow

1. Fork and create a feature branch from `main`
2. Make changes, run `ruff check exptrack/ tests/` and `pytest`
3. Submit a PR with a clear description
