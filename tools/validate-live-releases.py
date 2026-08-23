#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Download and inspect current CRHY release bundles without installing them."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile

from spaced_welcome.catalog import load_catalog
from spaced_welcome.installer import Installer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("keys", nargs="*", help="catalog keys; defaults to every GitHub app")
    args = parser.parse_args()
    catalog = load_catalog()
    apps = (
        [catalog.get(key) for key in args.keys]
        if args.keys
        else [app for app in catalog.apps if app.source_type == "github-release"]
    )
    with tempfile.TemporaryDirectory(prefix="spaced-welcome-live-validation-") as cache:
        os.environ["SPACED_WELCOME_CACHE_DIR"] = cache
        installer = Installer(
            catalog,
            callback=lambda event: print(
                f"{event.get('name', 'Installer')}: {event.get('message', event['event'])}",
                flush=True,
            ),
        )
        for app in apps:
            asset = installer.resolve(app)
            bundle = installer.download(app, asset)
            ref = installer.inspect_bundle(app, bundle)
            print(f"PASS {app.key}: {ref} ({Path(bundle).stat().st_size} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
