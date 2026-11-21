# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep post-install setup out of the installation medium's live session."""

from pathlib import Path


REBOOT_MESSAGE = (
    "Spaced Welcome cannot install applications in the live installer session. "
    "Finish installing Spaced Linux with Calamares, then restart your computer "
    "and boot from the installed drive. Follow the restart prompt before removing "
    "the installation USB. Open Spaced Welcome after logging into your installed "
    "system. If installation is still running, wait for it to finish first."
)


def is_live_session() -> bool:
    # The kernel flag survives unmounting the installation medium. Do not use
    # usernames or a persistent marker that could be copied into the target.
    if any(Path(path).exists() for path in (
        "/run/live/medium", "/lib/live/mount/medium",
    )):
        return True
    try:
        return "boot=live" in Path("/proc/cmdline").read_text().split()
    except OSError:
        # If boot context cannot be checked, do not mutate an unknown system.
        return True
