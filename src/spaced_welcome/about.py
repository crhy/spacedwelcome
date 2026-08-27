# SPDX-License-Identifier: GPL-3.0-or-later
"""About details for the Spaced Welcome first-run window."""

from __future__ import annotations

from pathlib import Path

from . import __version__


HOMEPAGE_URL = "https://spacedlinux.com"
HOMEPAGE_LABEL = "SpacedLinux.com"

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _repository_version() -> str | None:
    try:
        value = (_REPOSITORY_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def display_version() -> str:
    """Return the version string to show in the window."""

    return _repository_version() or __version__
