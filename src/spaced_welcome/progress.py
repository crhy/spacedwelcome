# SPDX-License-Identifier: GPL-3.0-or-later
"""GTK-independent progress model used by the UI and its tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProgressModel:
    rows: dict[str, str] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)
    summary: str = "Ready"

    def apply(self, event: dict[str, Any]) -> None:
        kind = str(event.get("event", "detail"))
        app_key = str(event.get("app", ""))
        name = str(event.get("name", app_key or "Installer"))
        source = str(event.get("source", ""))
        message = str(event.get("message", "")).strip()

        if kind == "app-start":
            status = f"Installing {name} from {source}…"
            self.rows[app_key] = status
            self.summary = status
        elif kind == "app-success":
            status = f"Installed {name} from {source}"
            self.rows[app_key] = status
            self.summary = status
        elif kind == "app-skipped":
            status = message or f"Skipped {name}"
            self.rows[app_key] = status
            self.summary = status
        elif kind == "app-failure":
            status = f"Failed: {message}" if message else f"Failed to install {name}"
            self.rows[app_key] = status
            self.summary = status
        elif kind == "summary":
            self.summary = message
        elif message:
            self.summary = message

        if message:
            prefix = name if app_key else "Installer"
            self.details.append(f"{prefix}: {message}")
