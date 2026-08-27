# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve, validate, and install Flatpak applications."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

from .catalog import App, Catalog, CatalogError


EventCallback = Callable[[dict[str, Any]], None]
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REMOTE_DESCRIPTORS = {
    "flathub": "https://flathub.org/repo/flathub.flatpakrepo",
    "spaced-github": "https://crhy.github.io/spacedbazaar/spaced-github.flatpakrepo",
}
REMOTE_URLS = {
    "flathub": "https://dl.flathub.org/repo/",
    "spaced-github": "https://crhy.github.io/spacedbazaar/flatpak-repo/",
}


class InstallError(RuntimeError):
    """An actionable remote or installation failure."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str


class Installer:
    """Install catalog entries while emitting structured progress events."""

    def __init__(
        self,
        catalog: Catalog,
        callback: EventCallback | None = None,
    ) -> None:
        self.catalog = catalog
        self.callback = callback or (lambda _event: None)
        self.flatpak = os.environ.get("SPACED_WELCOME_FLATPAK", "/usr/bin/flatpak")
        self.retry_delay = float(os.environ.get("SPACED_WELCOME_RETRY_DELAY", "2"))
        self.max_attempts = max(1, int(os.environ.get("SPACED_WELCOME_ATTEMPTS", "3")))

    def emit(self, event: str, app: App | None = None, **values: Any) -> None:
        payload: dict[str, Any] = {"event": event}
        if app is not None:
            payload.update(
                {
                    "app": app.key,
                    "name": app.name,
                    "app_id": app.app_id,
                    "source": app.source_label,
                }
            )
        payload.update({key: value for key, value in values.items() if value is not None})
        self.callback(payload)

    @staticmethod
    def _command_env() -> dict[str, str]:
        environment = os.environ.copy()
        environment["LC_ALL"] = "C.UTF-8"
        return environment

    def _run_capture(
        self, argv: list[str], *, timeout: int = 120, app: App | None = None
    ) -> CommandResult:
        try:
            result = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=timeout,
                env=self._command_env(),
            )
        except FileNotFoundError as error:
            raise InstallError(f"Required command is missing: {argv[0]}") from error
        except subprocess.TimeoutExpired as error:
            raise InstallError(f"Command timed out after {timeout} seconds: {argv[0]}") from error
        output = result.stdout.strip()
        if output:
            for line in output.splitlines():
                self.emit("detail", app, message=line.strip())
        return CommandResult(result.returncode, output)

    def _run_stream(self, argv: list[str], *, app: App | None = None) -> CommandResult:
        """Run a command and relay newline or carriage-return progress records."""

        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0,
                env=self._command_env(),
            )
        except FileNotFoundError as error:
            raise InstallError(f"Required command is missing: {argv[0]}") from error

        assert process.stdout is not None
        chunks: list[str] = []
        current: list[str] = []
        last_line = ""
        while True:
            character = process.stdout.read(1)
            if character == "":
                break
            chunks.append(character)
            if character in {"\n", "\r"}:
                line = "".join(current).strip()
                current.clear()
                if line and line != last_line:
                    self.emit("detail", app, message=line)
                    last_line = line
            else:
                current.append(character)
        line = "".join(current).strip()
        if line and line != last_line:
            self.emit("detail", app, message=line)
        return CommandResult(process.wait(), "".join(chunks).strip())

    def ensure_remote(self, name: str, app: App | None = None) -> None:
        try:
            descriptor_url = REMOTE_DESCRIPTORS[name]
            expected_url = REMOTE_URLS[name]
        except KeyError as error:
            raise InstallError(f"Unsupported Flatpak source: {name}") from error
        remotes = self._run_capture(
            [self.flatpak, "remotes", "--user", "--columns=name,url"], app=app
        )
        if remotes.returncode == 0:
            for line in remotes.output.splitlines():
                remote_name, separator, remote_url = line.partition("\t")
                if remote_name.strip() != name:
                    continue
                if not separator or remote_url.strip().rstrip("/") != expected_url.rstrip("/"):
                    raise InstallError(
                        f"The existing {name} remote has an unexpected URL; "
                        "remove or repair it before installing applications"
                    )
                return
        packaged = Path(f"/usr/share/flatpak/remotes.d/{name}.flatpakrepo")
        descriptor = str(packaged) if packaged.is_file() else descriptor_url
        self.emit("phase", app, phase="remote", message=f"Adding the {name} signed remote")
        result = self._run_stream(
            [
                self.flatpak,
                "remote-add",
                "--user",
                "--if-not-exists",
                name,
                descriptor,
            ],
            app=app,
        )
        if result.returncode != 0:
            raise InstallError(f"Could not configure {name} for this user")

    def _flatpak_info(self, app: App, user_only: bool = False) -> bool:
        command = [self.flatpak, "info"]
        if user_only:
            command.append("--user")
        command.append(app.app_id)
        result = self._run_capture(command, timeout=30, app=app)
        return result.returncode == 0

    def _install_command(self, app: App, remote: str) -> bool:
        command = [
            self.flatpak,
            "install",
            "--user",
            "--noninteractive",
            "-y",
            remote,
            f"{app.app_id}//{app.branch}",
        ]

        for attempt in range(1, self.max_attempts + 1):
            self.emit(
                "phase",
                app,
                phase="install",
                attempt=attempt,
                attempts=self.max_attempts,
                message=f"Installing {app.name} from {app.source_label} "
                f"(attempt {attempt} of {self.max_attempts})",
            )
            result = self._run_stream(command, app=app)
            if result.returncode == 0 and self._flatpak_info(app, user_only=True):
                return True
            if attempt < self.max_attempts:
                self.emit(
                    "detail",
                    app,
                    message=f"Install attempt {attempt} failed; retrying",
                )
                if self.retry_delay > 0:
                    time.sleep(self.retry_delay * attempt)
        return False

    @staticmethod
    def _seed_audacious_layout(app: App) -> None:
        if app.key != "audacious":
            return
        config_file = Path.home() / ".var/app/org.atheme.audacious/config/audacious/config"
        if config_file.exists():
            return
        config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        config_file.write_text(
            "[skins]\n"
            "player_x=20\nplayer_y=20\nplaylist_visible=TRUE\n"
            "playlist_x=20\nplaylist_y=136\nplaylist_width=275\nplaylist_height=232\n",
            encoding="utf-8",
        )
        config_file.chmod(0o600)

    def install_app(self, app: App) -> bool:
        self.emit(
            "app-start",
            app,
            message=f"Installing {app.name} from {app.source_label}",
        )
        try:
            if app.preinstalled:
                if not self._flatpak_info(app):
                    raise InstallError(
                        f"{app.name} should be preinstalled by Spaced Linux but is missing; "
                        "repair or update the OS package"
                    )
                self.emit(
                    "app-skipped",
                    app,
                    message=f"{app.name} is already installed with Spaced Linux",
                )
                return True

            if self._flatpak_info(app):
                self.emit(
                    "app-skipped",
                    app,
                    message=f"{app.name} is already installed",
                )
                return True

            if not BRANCH_RE.fullmatch(app.branch):
                raise InstallError(f"Unsafe Flatpak branch configured for {app.name}: {app.branch}")
            remote = "spaced-github" if app.source_type == "spaced-github" else "flathub"
            self.ensure_remote(remote, app)
            if not self._install_command(app, remote):
                raise InstallError(
                    f"{app.name} could not be installed after {self.max_attempts} attempts"
                )
            self._seed_audacious_layout(app)
            self.emit(
                "app-success",
                app,
                message=f"Installed {app.name} from {app.source_label}",
            )
            return True
        except (CatalogError, InstallError, OSError) as error:
            self.emit("app-failure", app, message=str(error))
            return False

    def install(self, apps: Iterable[App]) -> bool:
        selected = list(apps)
        if not selected:
            self.emit("summary", message="No applications were selected")
            return True
        succeeded = 0
        failed: list[App] = []
        for app in selected:
            if self.install_app(app):
                succeeded += 1
            else:
                failed.append(app)
        self.refresh_menus()
        if failed:
            names = ", ".join(app.name for app in failed)
            self.emit(
                "summary",
                success=False,
                succeeded=succeeded,
                failed=len(failed),
                message=f"Installed {succeeded} application(s); failed: {names}",
            )
            return False
        self.emit(
            "summary",
            success=True,
            succeeded=succeeded,
            failed=0,
            message=f"Installed {succeeded} application(s) successfully",
        )
        return True

    def refresh_menus(self) -> None:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        applications = data_home / "flatpak/exports/share/applications"
        updater = shutil.which("update-desktop-database")
        if updater and applications.is_dir():
            self._run_capture([updater, "-q", str(applications)], timeout=30)
        menu_updater = shutil.which("xdg-desktop-menu")
        if menu_updater:
            self._run_capture([menu_updater, "forceupdate", "--mode", "user"], timeout=30)
