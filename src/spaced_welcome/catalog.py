# SPDX-License-Identifier: GPL-3.0-or-later
"""Load and validate the Spaced Welcome application catalog."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any


DEFAULT_CATALOG = Path("/usr/share/spaced-welcome/catalog.json")
SOURCE_ROOT_CATALOG = Path(__file__).resolve().parents[2] / "data" / "catalog.json"
APP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CatalogError(ValueError):
    """Raised when catalog data is unsafe or inconsistent."""


@dataclass(frozen=True)
class App:
    key: str
    name: str
    app_id: str
    description: str
    source_type: str
    suggested: bool
    preinstalled: bool
    branch: str = "master"

    @property
    def source_label(self) -> str:
        return "Spaced GitHub" if self.source_type == "spaced-github" else "Flathub"


class Catalog:
    def __init__(self, apps: list[App]):
        self.apps = apps
        self._by_key = {app.key: app for app in apps}

    def get(self, key: str) -> App:
        try:
            return self._by_key[key]
        except KeyError as error:
            raise CatalogError(f"Unknown application: {key}") from error

    def suggested(self) -> list[App]:
        return [app for app in self.apps if app.suggested and not app.preinstalled]


def _catalog_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path)
    if os.environ.get("SPACED_WELCOME_CATALOG"):
        return Path(os.environ["SPACED_WELCOME_CATALOG"])
    if DEFAULT_CATALOG.is_file():
        return DEFAULT_CATALOG
    return SOURCE_ROOT_CATALOG


def load_catalog(path: str | os.PathLike[str] | None = None) -> Catalog:
    source_path = _catalog_path(path)
    try:
        payload: dict[str, Any] = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"Could not load catalog {source_path}: {error}") from error

    if payload.get("schema_version") != 1 or not isinstance(payload.get("apps"), list):
        raise CatalogError("Catalog must use schema_version 1 and contain an apps list")

    apps: list[App] = []
    seen_keys: set[str] = set()
    seen_ids: set[str] = set()
    for raw in payload["apps"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("source"), dict):
            raise CatalogError("Every catalog application needs a source object")
        key = raw.get("key", "")
        app_id = raw.get("app_id", "")
        name = raw.get("name", "")
        source = raw["source"]
        source_type = source.get("type")
        if not KEY_RE.fullmatch(key):
            raise CatalogError(f"Invalid application key: {key!r}")
        if key in seen_keys:
            raise CatalogError(f"Duplicate application key: {key}")
        if not APP_ID_RE.fullmatch(app_id):
            raise CatalogError(f"Invalid Flatpak application ID: {app_id!r}")
        if app_id in seen_ids:
            raise CatalogError(f"Duplicate Flatpak application ID: {app_id}")
        if not isinstance(name, str) or not name.strip():
            raise CatalogError(f"Application {key} has no display name")
        if source_type not in {"flathub", "spaced-github"}:
            raise CatalogError(f"Unsupported source for {name}: {source_type!r}")
        if set(source) != {"type"}:
            raise CatalogError(f"{name} source may only define its type")

        app = App(
            key=key,
            name=name.strip(),
            app_id=app_id,
            description=str(raw.get("description", "")).strip(),
            source_type=source_type,
            suggested=bool(raw.get("suggested", False)),
            preinstalled=bool(raw.get("preinstalled", False)),
            branch=str(raw.get("branch", "master")),
        )
        if app.preinstalled and app.suggested:
            raise CatalogError(f"Preinstalled application {name} cannot be suggested")
        seen_keys.add(key)
        seen_ids.add(app_id)
        apps.append(app)

    return Catalog(apps)
