# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import unittest

from spaced_welcome.progress import ProgressModel


class ProgressModelTests(unittest.TestCase):
    def test_ui_names_each_application_and_source_while_installing(self):
        model = ProgressModel()
        model.apply(
            {
                "event": "app-start",
                "app": "libreoffice",
                "name": "LibreOffice",
                "source": "Flathub",
                "message": "Installing LibreOffice from Flathub",
            }
        )
        self.assertEqual(
            model.rows["libreoffice"],
            "Installing LibreOffice from Flathub…",
        )
        model.apply(
            {
                "event": "app-start",
                "app": "cards-with-cats",
                "name": "Cards with Cats",
                "source": "GitHub",
                "message": "Installing Cards with Cats from GitHub",
            }
        )
        self.assertEqual(
            model.rows["cards-with-cats"],
            "Installing Cards with Cats from GitHub…",
        )
        self.assertIn("LibreOffice: Installing LibreOffice from Flathub", model.details)
        self.assertIn("Cards with Cats: Installing Cards with Cats from GitHub", model.details)

    def test_failure_is_actionable_and_visible_in_details(self):
        model = ProgressModel()
        model.apply(
            {
                "event": "app-failure",
                "app": "voice2text",
                "name": "Voice2Text AI",
                "source": "GitHub",
                "message": "SHA-256 verification failed; the download was discarded",
            }
        )
        self.assertIn("SHA-256", model.rows["voice2text"])
        self.assertIn("discarded", model.details[-1])


if __name__ == "__main__":
    unittest.main()

