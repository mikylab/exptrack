"""Tests for the CLI *parser*, not the command functions.

Every other CLI test calls `cmd_*` directly with a hand-built SimpleNamespace,
so a subcommand can be completely undispatchable from the shell while the whole
suite stays green. That is exactly what happened: the subparsers' `dest` was
`cmd`, which collided with the `--cmd` option on run-start/run-finish, and the
option's `""` default overwrote the subcommand name — `exptrack run-finish ID`
printed top-level help and exited 0, leaving the run stuck `running`.
"""
from __future__ import annotations

import argparse

from exptrack.cli.main import _DISPATCH, _build_parser


def _subparsers_action(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError("top-level parser has no subparsers")


def _placeholder(action):
    """A token that satisfies *action*'s type/choices without meaning anything."""
    if action.choices:
        return str(next(iter(action.choices)))
    if action.type is int:
        return "1"
    if action.type is float:
        return "1.0"
    return "x"


def _minimal_argv(child):
    """Smallest argv that parses against subparser *child* — every required
    positional and every required option, and nothing else."""
    argv = []
    for a in child._actions:
        if a.option_strings:
            if not a.required:
                continue
            argv.append(a.option_strings[-1])
            if a.nargs != 0:
                argv.append(_placeholder(a))
            continue
        # positional
        if isinstance(a, argparse._SubParsersAction):  # e.g. `session show ...`
            name = next(iter(a.choices))
            argv.extend([name, *_minimal_argv(a.choices[name])])
            continue
        if a.nargs in ("?", "*", argparse.REMAINDER):
            continue
        count = a.nargs if isinstance(a.nargs, int) else 1
        argv.extend(_placeholder(a) for _ in range(count))
    return argv


def test_every_dispatch_key_has_a_subparser():
    """A name in _DISPATCH with no subparser can never be reached from argv."""
    registered = set(_subparsers_action(_build_parser()).choices)
    missing = sorted(set(_DISPATCH) - registered)
    assert not missing, f"_DISPATCH entries with no subparser: {missing}"


def test_every_subparser_has_a_dispatch_entry():
    """And the reverse: a subparser with no handler KeyErrors at dispatch."""
    registered = set(_subparsers_action(_build_parser()).choices)
    # run-start is handled by a pre-parse branch in main() before _DISPATCH.
    orphans = sorted(registered - set(_DISPATCH) - {"run-start"})
    assert not orphans, f"subparsers with no _DISPATCH entry: {orphans}"


def test_no_subcommand_option_shadows_the_subcommand_dest():
    """No subparser option may write to the dest holding the subcommand name.

    This is the general form of the run-finish bug: any option (or positional)
    whose dest matches the subparsers' dest silently overwrites the command
    name, and an option with a non-None default does it on *every* invocation,
    not just when the user passes the flag.
    """
    sub = _subparsers_action(_build_parser())
    dest = sub.dest
    assert dest != "cmd", "subcommand dest must not be 'cmd' (--cmd option exists)"
    for name, child in sub.choices.items():
        clashing = [a.option_strings or a.dest for a in child._actions if a.dest == dest]
        assert not clashing, f"{name}: option(s) {clashing} shadow subcommand dest {dest!r}"


def test_parsing_each_subcommand_preserves_its_name():
    """Parse a minimal real argv for every subcommand and check main() would
    dispatch it. The argv is derived from each subparser's own required
    arguments, so a new subcommand is covered without touching this test."""
    sub = _subparsers_action(_build_parser())
    for name in sorted(set(sub.choices) - {"run-start"}):
        argv = [name, *_minimal_argv(sub.choices[name])]
        parser = _build_parser()
        try:
            args = parser.parse_args(argv)
        except SystemExit as e:  # pragma: no cover - only on a real regression
            raise AssertionError(f"{name}: argv {argv} failed to parse (exit {e.code})") from e
        got = getattr(args, sub.dest, None)
        assert got == name, f"{name}: parsed subcommand is {got!r}, not {name!r}"
        assert got in _DISPATCH, f"{name}: parsed name is not dispatchable"


def test_run_finish_keeps_its_cmd_option():
    """--cmd on run-finish must still land on args.cmd (pipeline_cmds reads it)."""
    args = _build_parser().parse_args(["run-finish", "abc123", "--cmd", "python train.py"])
    assert args.cmd == "python train.py"
    assert args.id == "abc123"
