# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spaced_welcome.catalog import CatalogError, load_catalog


class CatalogTests(unittest.TestCase):
    def test_verified_catalog_ids_and_sources(self):
        catalog = load_catalog()
        expected = {
            "spacedbazaar": "io.github.crhy.SpacedBazaar",
            "voice2text": "io.github.crhy.voice2textai",
            "cards-with-cats": "io.github.crhy.CardsWithCats",
            "brutal-chess": "io.github.crhy.BrutalChess",
            "spaced-update": "org.spacedlinux.SpacedUpdate",
        }
        self.assertEqual({key: catalog.get(key).app_id for key in expected}, expected)
        for key in expected:
            self.assertEqual(catalog.get(key).source_type, "spaced-github")
        self.assertFalse(catalog.get("spacedbazaar").preinstalled)
        self.assertTrue(catalog.get("spacedbazaar").suggested)
        self.assertEqual(
            [app.key for app in catalog.suggested() if app.source_type == "spaced-github"],
            ["spacedbazaar", "voice2text", "cards-with-cats", "brutal-chess", "spaced-update"],
        )
        for key in ("audacious", "brave", "libreoffice", "vlc"):
            self.assertEqual(catalog.get(key).branch, "stable")

    def test_catalog_requires_an_explicit_branch(self):
        payload = {
            "schema_version": 1,
            "apps": [{
                "key": "missing-branch",
                "name": "Missing Branch",
                "app_id": "io.example.MissingBranch",
                "source": {"type": "flathub"},
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "explicit valid Flatpak branch"):
                load_catalog(path)

    def test_catalog_rejects_source_coordinates_outside_central_policy(self):
        payload = {
            "schema_version": 1,
            "apps": [
                {
                    "key": "unsafe",
                    "name": "Unsafe",
                    "app_id": "io.example.Unsafe",
                    "source": {"type": "spaced-github", "repository": "someone/unsafe"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "source may only define its type"):
                load_catalog(path)

    def test_catalog_rejects_obsolete_direct_release_source(self):
        payload = {
            "schema_version": 1,
            "apps": [
                {
                    "key": "old",
                    "name": "Old",
                    "app_id": "io.example.Old",
                    "source": {"type": "github-release"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "Unsupported source"):
                load_catalog(path)


if __name__ == "__main__":
    unittest.main()
