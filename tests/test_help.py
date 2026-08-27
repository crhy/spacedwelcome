# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import unittest

from spaced_welcome.help import (
    BAZAAR_APP_ID,
    SUGGESTIONS,
    AppSuggestion,
    bazaar_command,
)


class HelpSuggestionsTests(unittest.TestCase):
    def test_expected_task_links_open_exact_bazaar_appstream_pages(self):
        expected = {
            "Edit video": "appstream://org.kde.kdenlive",
            "Edit photos": "appstream://org.gimp.GIMP",
            "Record music": "appstream://org.ardour.Ardour",
            "Edit audio": "appstream://org.tenacityaudio.Tenacity",
            "Play Wii and GameCube games": "appstream://org.DolphinEmu.dolphin-emu",
            "Read email": "appstream://org.mozilla.thunderbird",
            "Record or stream video": "appstream://com.obsproject.Studio",
            "Write code": "appstream://com.vscodium.codium",
            "Play popular games": "appstream://com.valvesoftware.Steam",
        }
        self.assertEqual({item.goal: item.uri for item in SUGGESTIONS}, expected)

    def test_command_opens_the_page_in_spacedbazaar(self):
        command = bazaar_command("/usr/bin/flatpak", SUGGESTIONS[0])
        self.assertEqual(
            command,
            [
                "/usr/bin/flatpak",
                "run",
                BAZAAR_APP_ID,
                "appstream://org.kde.kdenlive",
            ],
        )

    def test_invalid_app_id_is_rejected(self):
        suggestion = AppSuggestion("Unsafe", "Unsafe", "../unsafe", "Unsafe")
        with self.assertRaisesRegex(ValueError, "Invalid suggested application ID"):
            _ = suggestion.uri


if __name__ == "__main__":
    unittest.main()
