"""
exptrack/cli — Terminal interface

Re-exports main() so existing entry points work.
"""
from .main import main

__all__ = ["main"]
