# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line interface used by the Welcome UI and administrators."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .catalog import Catalog, CatalogError, load_catalog
from .installer import InstallError, Installer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spaced-welcome-install",
        description="List and install Spaced Linux application suggestions.",
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--list", action="store_true", help="list catalog applications")
    actions.add_argument(
        "--install",
        metavar="SELECTION",
        help="install 'suggested', 'all', one key, or comma-separated keys",
    )
    parser.add_argument("--json", action="store_true", help="print list output as JSON")
    parser.add_argument(
        "--events",
        action="store_true",
        help="emit newline-delimited JSON progress during installation",
    )
    parser.add_argument("--catalog", metavar="PATH", help="override the catalog path")
    return parser


def _list(catalog: Catalog, as_json: bool) -> int:
    rows = [
        {
            "key": app.key,
            "name": app.name,
            "app_id": app.app_id,
            "source": app.source_label,
            "suggested": app.suggested,
            "preinstalled": app.preinstalled,
        }
        for app in catalog.apps
    ]
    if as_json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    for row in rows:
        flags = []
        if row["preinstalled"]:
            flags.append("preinstalled")
        if row["suggested"]:
            flags.append("suggested")
        suffix = f" ({', '.join(flags)})" if flags else ""
        print(f"{row['key']:<18} {row['name']:<22} {row['source']}{suffix}")
    return 0


def _selection(catalog: Catalog, value: str) -> list:
    if value == "suggested":
        return catalog.suggested()
    if value == "all":
        return [app for app in catalog.apps if not app.preinstalled]
    keys = [key.strip() for key in value.split(",") if key.strip()]
    if not keys:
        raise CatalogError("No application keys were supplied")
    return [catalog.get(key) for key in keys]


def _event_writer(events: bool):
    if events:
        def emit(payload: dict[str, Any]) -> None:
            print(json.dumps(payload, sort_keys=True), flush=True)
        return emit

    def emit(payload: dict[str, Any]) -> None:
        message = payload.get("message")
        if message:
            print(message, flush=True)
    return emit


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        if args.list:
            return _list(catalog, args.json)

        installer = Installer(catalog, callback=_event_writer(args.events))
        selected = _selection(catalog, args.install)
        return 0 if installer.install(selected) else 1
    except (CatalogError, InstallError, OSError, ValueError) as error:
        if args.events:
            print(json.dumps({"event": "fatal", "message": str(error)}, sort_keys=True))
        else:
            print(f"spaced-welcome-install: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
