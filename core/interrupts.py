"""Shared interruption primitives for cooperative job control."""

from __future__ import annotations


class GenerationCancelled(RuntimeError):
    """Raised when a running generation task is canceled by user."""

