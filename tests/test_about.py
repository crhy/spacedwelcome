# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spaced_welcome import __version__
from spaced_welcome import about
from spaced_welcome.about import display_version, HOMEPAGE_LABEL, HOMEPAGE_URL


class AboutTests(unittest.TestCase):
    def test_homepage_points_at_spacedlinux_com(self):
        self.assertEqual(HOMEPAGE_URL, "https://spacedlinux.com")
        self.assertEqual(HOMEPAGE_LABEL, "SpacedLinux.com")

    def test_display_version_matches_repository_version_file(self):
        self.assertEqual((about._REPOSITORY_ROOT / "VERSION").read_text(encoding="utf-8").strip(), __version__)
        self.assertEqual(display_version(), __version__)

    def test_display_version_falls_back_to_package_version(self):
        original = about._REPOSITORY_ROOT
        with tempfile.TemporaryDirectory() as directory:
            about._REPOSITORY_ROOT = Path(directory)
            self.addCleanup(setattr, about, "_REPOSITORY_ROOT", original)
        self.assertEqual(display_version(), __version__)

    def test_display_version_reads_repository_file_when_present(self):
        original = about._REPOSITORY_ROOT
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            about._REPOSITORY_ROOT = Path(directory)
            self.addCleanup(setattr, about, "_REPOSITORY_ROOT", original)
            self.assertEqual(display_version(), "9.9.9")

    def test_version_format(self):
        self.assertRegex(display_version(), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
