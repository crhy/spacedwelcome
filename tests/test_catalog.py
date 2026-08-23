# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spaced_welcome.catalog import CatalogError, load_catalog, normalize_arch


class CatalogTests(unittest.TestCase):
    def test_verified_catalog_ids_and_sources(self):
        catalog = load_catalog()
        expected = {
            "spacedbazaar": "io.github.crhy.SpacedBazaar",
            "voice2text": "io.github.crhy.voice2textai",
            "cards-with-cats": "io.github.crhy.ScumWithCats",
            "brutal-chess": "io.github.crhy.BrutalChess",
            "spaced-update": "org.spacedlinux.SpacedUpdate",
        }
        self.assertEqual(
            {key: catalog.get(key).app_id for key in expected},
            expected,
        )
        for key in expected:
            self.assertEqual(catalog.get(key).source_type, "github-release")
        self.assertTrue(catalog.get("spacedbazaar").preinstalled)
        self.assertFalse(catalog.get("spacedbazaar").suggested)
        self.assertNotIn("spacedbazaar", [app.key for app in catalog.suggested()])
        self.assertEqual(catalog.get("spacedbazaar").branch, "master")
        self.assertEqual(catalog.get("voice2text").branch, "master")
        for key in ("cards-with-cats", "brutal-chess", "spaced-update"):
            self.assertEqual(catalog.get(key).branch, "stable")

    def test_exact_asset_names_are_derived_per_release_and_arch(self):
        catalog = load_catalog()
        self.assertEqual(
            catalog.get("spacedbazaar").asset_name("aarch64", "0.1.2"),
            "SpacedBazaar-aarch64.flatpak",
        )
        self.assertEqual(
            catalog.get("cards-with-cats").asset_name("x86_64", "v0.3.3"),
            "ScumWithCats-0.3.3.flatpak",
        )
        self.assertEqual(
            catalog.get("brutal-chess").asset_name("x86_64", "v0.2.1"),
            "BrutalChess-0.2.1.flatpak",
        )
        self.assertEqual(
            catalog.get("spaced-update").asset_name("x86_64", "8.26.4.0.2"),
            "SpacedUpdate-8.26.4.0.2-x86_64.flatpak",
        )

    def test_architecture_aliases_and_unsupported_architecture(self):
        self.assertEqual(normalize_arch("amd64"), "x86_64")
        self.assertEqual(normalize_arch("arm64"), "aarch64")
        with self.assertRaisesRegex(CatalogError, "Unsupported architecture"):
            normalize_arch("riscv64")

    def test_catalog_rejects_non_crhy_repository(self):
        payload = {
            "schema_version": 1,
            "apps": [
                {
                    "key": "unsafe",
                    "name": "Unsafe",
                    "app_id": "io.example.Unsafe",
                    "source": {
                        "type": "github-release",
                        "repository": "someone/unsafe",
                        "assets": {"x86_64": {"name": "Unsafe.flatpak"}},
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "Unsafe GitHub repository"):
                load_catalog(path)


if __name__ == "__main__":
    unittest.main()
