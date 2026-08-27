# SPDX-License-Identifier: GPL-3.0-or-later
"""Task-oriented application suggestions for the Welcome help page."""

from __future__ import annotations

import re
from dataclasses import dataclass

BAZAAR_APP_ID = "io.github.crhy.SpacedBazaar"
APP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class AppSuggestion:
    goal: str
    app_name: str
    app_id: str
    description: str

    @property
    def uri(self) -> str:
        if not APP_ID_RE.fullmatch(self.app_id):
            raise ValueError(f"Invalid suggested application ID: {self.app_id!r}")
        return f"appstream://{self.app_id}"


SUGGESTIONS = (
    AppSuggestion(
        "Edit video", "Kdenlive", "org.kde.kdenlive", "A full-featured video editor."
    ),
    AppSuggestion("Edit photos", "GIMP", "org.gimp.GIMP", "Create and retouch images."),
    AppSuggestion(
        "Record music", "Ardour", "org.ardour.Ardour", "Record, mix, and master audio."
    ),
    AppSuggestion(
        "Edit audio",
        "Tenacity",
        "org.tenacityaudio.Tenacity",
        "Record and edit sound quickly.",
    ),
    AppSuggestion(
        "Play Wii and GameCube games",
        "Dolphin Emulator",
        "org.DolphinEmu.dolphin-emu",
        "Run legally obtained Wii and GameCube games.",
    ),
    AppSuggestion(
        "Read email",
        "Thunderbird",
        "org.mozilla.thunderbird",
        "Email, calendars, and contacts.",
    ),
    AppSuggestion(
        "Record or stream video",
        "OBS Studio",
        "com.obsproject.Studio",
        "Capture the desktop, cameras, and live streams.",
    ),
    AppSuggestion(
        "Write code",
        "VSCodium",
        "com.vscodium.codium",
        "A community build of the VS Code editor.",
    ),
    AppSuggestion(
        "Play popular games",
        "Steam",
        "com.valvesoftware.Steam",
        "Browse and play your Steam library.",
    ),
)


def bazaar_command(flatpak: str, suggestion: AppSuggestion | None = None) -> list[str]:
    command = [flatpak, "run", BAZAAR_APP_ID]
    if suggestion is not None:
        command.append(suggestion.uri)
    return command
