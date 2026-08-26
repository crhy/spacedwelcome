# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve, validate, and install Flatpak applications."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import unquote, urlparse

from .catalog import App, Catalog, CatalogError, normalize_arch


EventCallback = Callable[[dict[str, Any]], None]
DIGEST_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
IMPORT_RE = re.compile(r"(?:^|\s)(app/[A-Za-z0-9._-]+/[A-Za-z0-9_-]+/[A-Za-z0-9._-]+)(?:\s|$)")


class InstallError(RuntimeError):
    """An actionable resolver, validation, or installation failure."""


@dataclass(frozen=True)
class ReleaseAsset:
    repository: str
    tag: str
    name: str
    url: str
    size: int
    digest: str | None
    asset_id: int | None
    app_id: str
    arch: str
    branch: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str


def _default_cache_dir() -> Path:
    configured = os.environ.get("SPACED_WELCOME_CACHE_DIR")
    if configured:
        return Path(configured)
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "spaced-welcome"


class Installer:
    """Install catalog entries while emitting structured progress events."""

    def __init__(
        self,
        catalog: Catalog,
        callback: EventCallback | None = None,
        arch: str | None = None,
    ) -> None:
        self.catalog = catalog
        self.callback = callback or (lambda _event: None)
        self.arch = normalize_arch(arch)
        self.flatpak = os.environ.get("SPACED_WELCOME_FLATPAK", "/usr/bin/flatpak")
        self.ostree = os.environ.get("SPACED_WELCOME_OSTREE", "/usr/bin/ostree")
        self.curl = os.environ.get("SPACED_WELCOME_CURL", "/usr/bin/curl")
        self.api_root = os.environ.get(
            "SPACED_WELCOME_GITHUB_API_ROOT", "https://api.github.com"
        ).rstrip("/")
        if self.api_root != "https://api.github.com" and not os.environ.get(
            "SPACED_WELCOME_ALLOW_TEST_API"
        ):
            raise InstallError("A non-GitHub API endpoint is allowed only in the test harness")
        self.cache_dir = _default_cache_dir()
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

    @staticmethod
    def _validate_release_url(repository: str, tag: str, asset_name: str, url: str) -> None:
        parsed = urlparse(url)
        expected_path = f"/{repository}/releases/download/{tag}/{asset_name}"
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or unquote(parsed.path) != expected_path
        ):
            raise InstallError(
                f"GitHub returned an unexpected download URL for {asset_name}; refusing it"
            )

    def resolve(self, app: App) -> ReleaseAsset:
        if app.source_type != "github-release" or not app.repository:
            raise InstallError(f"{app.name} is installed from Flathub, not a GitHub release")
        if not BRANCH_RE.fullmatch(app.branch):
            raise InstallError(f"Unsafe Flatpak branch configured for {app.name}: {app.branch}")

        self.emit("phase", app, phase="resolve", message=f"Checking {app.repository} latest release")
        with tempfile.TemporaryDirectory(prefix="spaced-welcome-release-") as directory:
            response_path = Path(directory) / "release.json"
            api_url = f"{self.api_root}/repos/{app.repository}/releases/latest"
            result = self._run_capture(
                [
                    self.curl,
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "3",
                    "--retry-all-errors",
                    "--connect-timeout",
                    "15",
                    "--proto",
                    "=https",
                    "--proto-redir",
                    "=https",
                    "--header",
                    "Accept: application/vnd.github+json",
                    "--header",
                    "X-GitHub-Api-Version: 2022-11-28",
                    "--header",
                    "User-Agent: spaced-welcome/1.0.0",
                    "--output",
                    str(response_path),
                    api_url,
                ],
                timeout=90,
                app=app,
            )
            if result.returncode != 0:
                raise InstallError(f"Could not query the latest {app.repository} release")
            try:
                release = json.loads(response_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise InstallError(f"GitHub returned invalid release data for {app.name}") from error

        if release.get("draft") or release.get("prerelease"):
            raise InstallError(f"The latest {app.name} release is not stable")
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not tag or "/" in tag or tag in {".", ".."}:
            raise InstallError(f"GitHub returned an unsafe release tag for {app.name}")
        expected_name = app.asset_name(self.arch, tag)
        assets = [
            asset
            for asset in release.get("assets", [])
            if isinstance(asset, dict)
            and asset.get("name") == expected_name
            and asset.get("state", "uploaded") == "uploaded"
        ]
        if len(assets) != 1:
            raise InstallError(
                f"Expected exactly one {expected_name} asset on {app.repository} {tag}; "
                f"found {len(assets)}"
            )
        raw = assets[0]
        url = raw.get("browser_download_url")
        size = raw.get("size")
        if not isinstance(url, str):
            raise InstallError(f"The {expected_name} release asset has no download URL")
        if not isinstance(size, int) or size <= 0:
            raise InstallError(f"The {expected_name} release asset has an invalid size")
        self._validate_release_url(app.repository, tag, expected_name, url)

        digest = raw.get("digest")
        if digest is not None and (not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest)):
            raise InstallError(f"GitHub returned an invalid SHA-256 digest for {expected_name}")
        asset_id = raw.get("id") if isinstance(raw.get("id"), int) else None
        resolved = ReleaseAsset(
            repository=app.repository,
            tag=tag,
            name=expected_name,
            url=url,
            size=size,
            digest=digest,
            asset_id=asset_id,
            app_id=app.app_id,
            arch=self.arch,
            branch=app.branch,
        )
        self.emit(
            "resolved",
            app,
            phase="resolve",
            message=f"Resolved {expected_name} from {tag}",
            release=resolved.to_dict(),
        )
        return resolved

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_download(self, app: App, asset: ReleaseAsset, path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise InstallError(f"Downloaded file for {app.name} is missing or unsafe")
        actual_size = path.stat().st_size
        if actual_size != asset.size:
            raise InstallError(
                f"Downloaded {asset.name} is {actual_size} bytes; GitHub reports {asset.size} bytes"
            )
        actual_digest = self._sha256(path)
        if asset.digest:
            expected_digest = DIGEST_RE.fullmatch(asset.digest).group(1)  # type: ignore[union-attr]
            if actual_digest != expected_digest:
                raise InstallError(
                    f"SHA-256 verification failed for {asset.name}; the download was discarded"
                )
            message = f"Verified {asset.name} SHA-256 {actual_digest}"
        else:
            message = f"Verified {asset.name} size; GitHub did not publish a digest"
        self.emit("verified", app, phase="download", message=message, sha256=actual_digest)

    def download(self, app: App, asset: ReleaseAsset) -> Path:
        app_cache = self.cache_dir / app.key
        app_cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        final_path = app_cache / asset.name
        partial_path = app_cache / f".{asset.name}.part"
        for candidate in (final_path, partial_path):
            if candidate.is_symlink():
                candidate.unlink()

        if final_path.exists():
            try:
                self._verify_download(app, asset, final_path)
                self.emit("phase", app, phase="download", message=f"Using cached {asset.name}")
                return final_path
            except InstallError:
                final_path.unlink(missing_ok=True)

        self.emit(
            "phase",
            app,
            phase="download",
            message=f"Downloading {asset.name} from GitHub ({asset.size} bytes)",
        )
        result = self._run_stream(
            [
                self.curl,
                "--fail",
                "--location",
                "--progress-bar",
                "--show-error",
                "--retry",
                "3",
                "--retry-all-errors",
                "--connect-timeout",
                "15",
                "--proto",
                "=https",
                "--proto-redir",
                "=https",
                "--continue-at",
                "-",
                "--output",
                str(partial_path),
                asset.url,
            ],
            app=app,
        )
        if result.returncode != 0:
            raise InstallError(f"Download failed for {asset.name}; retry the installation")
        try:
            self._verify_download(app, asset, partial_path)
        except InstallError:
            partial_path.unlink(missing_ok=True)
            raise
        os.replace(partial_path, final_path)
        return final_path

    def inspect_bundle(self, app: App, bundle: Path) -> str:
        if bundle.suffix != ".flatpak":
            raise InstallError(f"Refusing bundle without a .flatpak suffix: {bundle.name}")
        # The import repository must live where the host can see it. Inside the
        # Spaced Welcome Flatpak, ostree and flatpak execute on the host via
        # flatpak-spawn, so the sandbox-private /tmp is not readable by them.
        # The xdg-cache based cache directory is shared with the host.
        repo = self.cache_dir / "import" / app.key
        if repo.exists():
            shutil.rmtree(repo)
        repo.parent.mkdir(parents=True, exist_ok=True)
        repo.mkdir(mode=0o700)
        init = self._run_capture(
            [self.ostree, f"--repo={repo}", "init", "--mode=archive-z2"], app=app
        )
        if init.returncode != 0:
            raise InstallError("Could not create the temporary Flatpak inspection repository")
        imported = self._run_capture(
            [
                self.flatpak,
                "build-import-bundle",
                "--no-update-summary",
                str(repo),
                str(bundle),
            ],
            timeout=300,
            app=app,
        )
        try:
            if imported.returncode != 0:
                raise InstallError(f"{bundle.name} is not a valid Flatpak bundle")
            refs = sorted(set(IMPORT_RE.findall(imported.output)))
        finally:
            shutil.rmtree(repo, ignore_errors=True)
        if len(refs) != 1:
            raise InstallError(f"Could not determine one Flatpak ref inside {bundle.name}")
        expected = f"app/{app.app_id}/{self.arch}/{app.branch}"
        if refs[0] != expected:
            raise InstallError(
                f"Flatpak ref mismatch for {bundle.name}: expected {expected}, found {refs[0]}"
            )
        self.emit(
            "verified",
            app,
            phase="inspect",
            message=f"Verified Flatpak ref {expected}",
            ref=expected,
        )
        return expected

    def ensure_flathub(self, app: App | None = None) -> None:
        remotes = self._run_capture(
            [self.flatpak, "remotes", "--user", "--columns=name"], app=app
        )
        names = {line.strip() for line in remotes.output.splitlines()}
        if remotes.returncode == 0 and "flathub" in names:
            return
        self.emit("phase", app, phase="remote", message="Adding the Flathub runtime remote")
        result = self._run_stream(
            [
                self.flatpak,
                "remote-add",
                "--user",
                "--if-not-exists",
                "flathub",
                "https://flathub.org/repo/flathub.flatpakrepo",
            ],
            app=app,
        )
        if result.returncode != 0:
            raise InstallError("Could not configure Flathub for this user")

    def _flatpak_info(self, app: App, user_only: bool = False) -> bool:
        command = [self.flatpak, "info"]
        if user_only:
            command.append("--user")
        command.append(app.app_id)
        result = self._run_capture(command, timeout=30, app=app)
        return result.returncode == 0

    def _install_command(self, app: App, bundle: Path | None = None) -> bool:
        if bundle is None:
            command = [
                self.flatpak,
                "install",
                "--user",
                "--noninteractive",
                "-y",
                "flathub",
                app.app_id,
            ]
        else:
            command = [
                self.flatpak,
                "install",
                "--user",
                "--noninteractive",
                "-y",
                str(bundle),
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

            self.ensure_flathub(app)
            bundle: Path | None = None
            if app.source_type == "github-release":
                asset = self.resolve(app)
                bundle = self.download(app, asset)
                self.inspect_bundle(app, bundle)
            if not self._install_command(app, bundle):
                raise InstallError(
                    f"{app.name} could not be installed after {self.max_attempts} attempts"
                )
            self._seed_audacious_layout(app)
            self.emit(
                "app-success",
                app,
                message=f"Installed {app.name} from {app.source_label}",
            )
            if bundle and not os.environ.get("SPACED_WELCOME_KEEP_DOWNLOADS"):
                bundle.unlink(missing_ok=True)
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
