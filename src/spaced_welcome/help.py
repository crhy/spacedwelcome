# SPDX-License-Identifier: GPL-3.0-or-later
"""Task-oriented application suggestions for the Welcome help page."""

from __future__ import annotations

import re
from dataclasses import dataclass

BAZAAR_APP_ID = "io.github.crhy.SpacedBazaar"
APP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]+$")

# Kept in the application so these first steps work without an Internet connection.
GUIDES = (
    (
        "Connect an Android phone",
        "1. Unlock the phone and connect a USB cable that supports data.\n"
        "2. Open the phone's USB notification and choose File Transfer (MTP).\n"
        "3. Open Home Folder (Caja), choose the phone in the sidebar, and copy files.\n"
        "4. Wait for copying to finish, then eject the phone in Caja before unplugging.\n\n"
        "If it only charges, try another data cable or USB port. If the connection stalls, "
        "close files using the phone, eject it in Caja, reconnect, unlock, and choose "
        "File Transfer again. In a VM, attach the phone through the VM's USB device menu first.",
        "https://support.google.com/android/answer/9064445?hl=en",
    ),
    (
        "Connect an iPhone or iPad",
        "1. Unlock the device, connect it with a data cable, and approve Trust This Computer "
        "on the device when asked.\n"
        "2. Open Home Folder (Caja) and select the device in the sidebar. Copy photos from "
        "the camera/media view or documents from apps that support file sharing.\n"
        "3. Finish copying and eject the device before unplugging.\n\n"
        "The files offered depend on the iOS version and each app's file-sharing support. "
        "This does not expose every app's private data. If access stops after an iOS update, "
        "apply Spaced Update, close device windows, eject and reconnect, then unlock and "
        "approve trust again. Try another cable or port if the device is absent. "
        "For a VM, attach the device through the VM's USB menu. Keep the originals until "
        "you have opened and checked the copied files.",
        "https://github.com/libimobiledevice/libimobiledevice",
    ),
    (
        "Open a Windows or NAS shared folder",
        "1. Connect both computers to the same trusted network. On the Windows computer "
        "or NAS, share a folder with a named account that has a password.\n"
        "2. In Home Folder (Caja), press Ctrl+L and enter smb://computer-name/share-name. "
        "Use the server's local IP address if its name does not resolve.\n"
        "3. Choose Registered User and enter that server account's username, password, "
        "and domain if your network requires one. A Windows sign-in PIN is not the account password.\n"
        "4. Bookmark the folder after connecting. Eject it from the sidebar when finished.\n\n"
        "If access fails, check the share name, account permissions, network connection, "
        "and the server's file-sharing firewall rules. After a password or network change, "
        "close files from the share, eject it, and reconnect. Keep authenticated sharing "
        "enabled; do not enable obsolete SMB1 or anonymous guest access to work around errors.",
        "https://help.gnome.org/gnome-help/nautilus-connect.html",
    ),
    (
        "Start a creative project",
        "Video: open Kdenlive below, create a project, import clips, drag them onto the "
        "timeline, then Render to make a playable video.\n"
        "Quick audio edits: open Tenacity, import or record sound, trim it, then export "
        "an audio file. Save the project separately to keep an editable copy.\n"
        "Music: open Ardour, create a session, select your audio device, add and arm a "
        "track, then record. Begin with headphones to avoid microphone feedback.\n"
        "Photos: open GIMP, edit a copy of your image, save XCF to retain layers, then "
        "export PNG or JPEG for sharing.\n"
        "Email: open Thunderbird and add your account; some providers require browser "
        "sign-in or an app password.\n\n"
        "Use each application's Help menu for its full manual. If a Flatpak cannot see "
        "a file, open it using the application's file chooser so the desktop can grant access.",
        "https://docs.kdenlive.org/en/getting_started/quickstart.html",
    ),
)


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
