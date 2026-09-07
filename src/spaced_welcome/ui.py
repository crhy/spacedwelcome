# SPDX-License-Identifier: GPL-3.0-or-later
"""GTK 3 first-run interface for Spaced Welcome."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .about import HOMEPAGE_LABEL, HOMEPAGE_URL, display_version
from .catalog import App, CatalogError, load_catalog
from .help import BAZAAR_APP_ID, GUIDES, SUGGESTIONS, AppSuggestion, bazaar_command
from .progress import ProgressModel


CSS = b"""
window.spaced-welcome, window.spaced-welcome .app-surface {
  background-color: #17191c;
  color: #f4f4f4;
}
.hero-title { font-size: 28px; font-weight: 700; color: #f4f4f4; }
.hero-subtitle { font-size: 14px; color: #b8bbc2; }
.choice-card {
  background-image: none;
  background-color: #1f2329;
  border: 1px solid #3a3f47;
  border-radius: 10px;
  padding: 13px 16px;
  color: #f4f4f4;
  box-shadow: none;
}
.choice-card:hover { background-color: #262b33; border-color: #6e9de8; }
.choice-card:active { background-color: #171a1f; border-color: #4f6bb0; }
.choice-title { font-size: 16px; font-weight: 700; color: #f4f4f4; }
.choice-detail, .app-detail { font-size: 11px; color: #b8bbc2; }
.choice-icon, .source-label { color: #6e9de8; }
.app-row { padding: 8px 10px; border-bottom: 1px solid #30343b; }
.app-name { font-weight: 700; color: #f4f4f4; }
.app-status { font-size: 11px; color: #c6c9cf; }
.status { font-size: 12px; color: #c6c9cf; }
.help-row {
  background-color: #1f2329;
  border: 1px solid #30343b;
  border-radius: 8px;
  padding: 10px 12px;
}
.help-goal { font-size: 14px; font-weight: 700; color: #f4f4f4; }
textview, textview text { background-color: #111316; color: #d9dce2; }
"""


class AppRow(Gtk.Box):
    def __init__(self, app: App):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.app = app
        self.get_style_context().add_class("app-row")

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        name = Gtk.Label(label=app.name, xalign=0)
        name.get_style_context().add_class("app-name")
        detail = Gtk.Label(label=app.description, xalign=0)
        detail.set_ellipsize(3)
        detail.get_style_context().add_class("app-detail")
        labels.pack_start(name, False, False, 0)
        labels.pack_start(detail, False, False, 0)
        self.pack_start(labels, True, True, 0)

        source = Gtk.Label(label=app.source_label)
        source.get_style_context().add_class("source-label")
        source.set_width_chars(8)
        self.pack_start(source, False, False, 0)

        self.status = Gtk.Label(label="Ready", xalign=0)
        self.status.set_width_chars(34)
        self.status.set_line_wrap(True)
        self.status.get_style_context().add_class("app-status")
        self.pack_start(self.status, False, False, 0)


class WelcomeWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Welcome to Spaced Linux")
        self.set_name("spaced-welcome")
        self.get_style_context().add_class("spaced-welcome")
        self.set_default_size(900, 720)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_border_width(0)
        self.catalog = load_catalog()
        self.model = ProgressModel()
        self.rows: dict[str, AppRow] = {}
        self.install_process: subprocess.Popen[str] | None = None
        self.running = False
        self.pending_bazaar: tuple[AppSuggestion | None] | None = None

        # Installed builds find these through hicolor normally. Add the source
        # tree while developing so screenshots and tests resolve the same art.
        source_icons = Path(__file__).resolve().parents[2] / "data/icons/hicolor"
        if source_icons.is_dir():
            Gtk.IconTheme.get_default().append_search_path(str(source_icons))

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        surface = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        surface.get_style_context().add_class("app-surface")
        surface.set_border_width(28)
        self.add(surface)

        title = Gtk.Label(label="Welcome to Spaced Linux")
        title.get_style_context().add_class("hero-title")
        surface.pack_start(title, False, False, 0)
        subtitle = Gtk.Label(
            label="Keep the base system lean. Add SpacedBazaar and suggested apps whenever you like."
        )
        subtitle.get_style_context().add_class("hero-subtitle")
        subtitle.set_margin_top(4)
        subtitle.set_margin_bottom(18)
        surface.pack_start(subtitle, False, False, 0)

        self.pages = Gtk.Stack()
        self.pages.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.pages.set_transition_duration(220)
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.pages)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_bottom(14)
        surface.pack_start(switcher, False, False, 0)
        surface.pack_start(self.pages, True, True, 0)

        setup_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.pages.add_titled(setup_page, "setup", "Set Up")

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.suggested_button = self._choice(
            "system-software-install", "Install Suggested Apps", "Flathub and signed Spaced GitHub apps"
        )
        self.suggested_button.connect("clicked", self._start_suggested_install)
        actions.pack_start(self.suggested_button, True, True, 0)
        self.bazaar_button = self._choice(
            "io.github.crhy.SpacedBazaar",
            "Open SpacedBazaar",
            "Install the app store if needed, then open it",
        )
        self.bazaar_button.connect("clicked", self._open_bazaar)
        actions.pack_start(self.bazaar_button, True, True, 0)
        self.nvidia_button = self._choice(
            "video-display", "NVIDIA Drivers", "Open the graphics driver setup"
        )
        self.nvidia_button.connect("clicked", self._open_nvidia_installer)
        actions.pack_start(self.nvidia_button, True, True, 0)
        setup_page.pack_start(actions, False, False, 0)

        apps_label = Gtk.Label(label="Suggested Applications", xalign=0)
        apps_label.get_style_context().add_class("choice-title")
        apps_label.set_margin_start(10)
        apps_label.set_margin_top(18)
        apps_label.set_margin_bottom(6)
        setup_page.pack_start(apps_label, False, False, 0)

        app_scroll = Gtk.ScrolledWindow()
        app_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        app_scroll.set_min_content_height(230)
        app_scroll.set_shadow_type(Gtk.ShadowType.IN)
        app_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        for app in self.catalog.suggested():
            row = AppRow(app)
            self.rows[app.key] = row
            app_box.pack_start(row, False, False, 0)
        app_scroll.add(app_box)
        setup_page.pack_start(app_scroll, True, True, 0)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.set_halign(Gtk.Align.CENTER)
        status_box.set_margin_top(12)
        self.spinner = Gtk.Spinner()
        status_box.pack_start(self.spinner, False, False, 0)
        self.status = Gtk.Label(label="Nothing else is installed until you choose.")
        self.status.get_style_context().add_class("status")
        status_box.pack_start(self.status, False, False, 0)
        surface.pack_start(status_box, False, False, 0)

        about_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        about_box.set_halign(Gtk.Align.CENTER)
        about_box.set_margin_top(10)
        self.version_label = Gtk.Label(label=f"Version {display_version()}")
        self.version_label.get_style_context().add_class("status")
        about_box.pack_start(self.version_label, False, False, 0)
        self.homepage_link = Gtk.LinkButton(uri=HOMEPAGE_URL, label=HOMEPAGE_LABEL)
        about_box.pack_start(self.homepage_link, False, False, 0)
        setup_page.pack_start(about_box, False, False, 0)

        self.details_expander = Gtk.Expander(label="Details")
        self.details_expander.set_margin_top(8)
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_min_content_height(125)
        detail_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.details = Gtk.TextView()
        self.details.set_editable(False)
        self.details.set_cursor_visible(False)
        self.details.set_monospace(True)
        self.details.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        detail_scroll.add(self.details)
        self.details_expander.add(detail_scroll)
        setup_page.pack_start(self.details_expander, False, False, 0)

        self.pages.add_titled(self._build_help_page(), "help", "Help & Apps")

        self.connect("destroy", self._on_destroy)

    @staticmethod
    def _choice(icon_name: str, heading: str, detail: str) -> Gtk.Button:
        button = Gtk.Button()
        button.get_style_context().add_class("choice-card")
        button.set_relief(Gtk.ReliefStyle.NONE)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)
        icon.get_style_context().add_class("choice-icon")
        row.pack_start(icon, False, False, 0)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        heading_label = Gtk.Label(label=heading, xalign=0)
        heading_label.get_style_context().add_class("choice-title")
        detail_label = Gtk.Label(label=detail, xalign=0)
        detail_label.set_line_wrap(True)
        detail_label.get_style_context().add_class("choice-detail")
        copy.pack_start(heading_label, False, False, 0)
        copy.pack_start(detail_label, False, False, 0)
        row.pack_start(copy, True, True, 0)
        button.add(row)
        return button

    def _build_help_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_border_width(4)

        desktop_heading = Gtk.Label(label="Desktop quick start", xalign=0)
        desktop_heading.get_style_context().add_class("choice-title")
        content.pack_start(desktop_heading, False, False, 0)
        desktop_help = Gtk.Label(
            label=(
                "Rotate the desktop cube with Ctrl+Alt+left-drag. Zoom with "
                "Shift+Super+mouse wheel (or Shift+Super+Up/Down). Capture an "
                "area with Shift+Print (or Ctrl+Shift+left-drag in Compiz). Draw with fire using "
                "Shift+Super+left-drag, then clear it with Shift+Super+C."
            ),
            xalign=0,
        )
        desktop_help.set_line_wrap(True)
        desktop_help.get_style_context().add_class("choice-detail")
        content.pack_start(desktop_help, False, False, 0)

        safety = Gtk.Label(
            label=(
                "Spaced Linux creates a Timeshift snapshot named “Fresh install” "
                "after the first installed-system boot. The system is fully "
                "configurable, but changing or removing system files can break it."
            ),
            xalign=0,
        )
        safety.set_line_wrap(True)
        safety.set_margin_bottom(10)
        safety.get_style_context().add_class("choice-detail")
        content.pack_start(safety, False, False, 0)

        for title, instructions, source_url in GUIDES:
            guide = Gtk.Expander(label=title)
            guide_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            guide_box.set_border_width(10)
            copy = Gtk.Label(label=instructions, xalign=0)
            copy.set_line_wrap(True)
            copy.set_selectable(True)
            guide_box.pack_start(copy, False, False, 0)
            source = Gtk.LinkButton.new_with_label(source_url, "More information online")
            source.set_halign(Gtk.Align.START)
            guide_box.pack_start(source, False, False, 0)
            guide.add(guide_box)
            content.pack_start(guide, False, False, 0)

        heading = Gtk.Label(label="What would you like to do?", xalign=0)
        heading.get_style_context().add_class("choice-title")
        content.pack_start(heading, False, False, 0)
        introduction = Gtk.Label(
            label=(
                "Choose an activity to open the recommended app directly in "
                "SpacedBazaar. The store is installed if needed; choose whether "
                "to install the recommended app when its page opens."
            ),
            xalign=0,
        )
        introduction.set_line_wrap(True)
        introduction.set_margin_bottom(6)
        introduction.get_style_context().add_class("choice-detail")
        content.pack_start(introduction, False, False, 0)

        for suggestion in SUGGESTIONS:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.get_style_context().add_class("help-row")
            copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            goal = Gtk.Label(label=suggestion.goal, xalign=0)
            goal.get_style_context().add_class("help-goal")
            detail = Gtk.Label(
                label=f"{suggestion.app_name} · {suggestion.description}", xalign=0
            )
            detail.set_line_wrap(True)
            detail.get_style_context().add_class("choice-detail")
            copy.pack_start(goal, False, False, 0)
            copy.pack_start(detail, False, False, 0)
            row.pack_start(copy, True, True, 0)
            open_button = Gtk.Button(label=f"Open {suggestion.app_name}")
            open_button.connect("clicked", self._open_suggestion, suggestion)
            row.pack_start(open_button, False, False, 0)
            content.pack_start(row, False, False, 0)

        scroll.add(content)
        return scroll

    def _append_detail(self, line: str) -> None:
        buffer = self.details.get_buffer()
        buffer.insert(buffer.get_end_iter(), f"{line}\n")
        mark = buffer.create_mark(None, buffer.get_end_iter(), False)
        self.details.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.suggested_button.set_sensitive(not running)
        self.bazaar_button.set_sensitive(not running)
        if running:
            self.spinner.show()
            self.spinner.start()
        else:
            self.spinner.stop()
            self.spinner.hide()

    def _start_suggested_install(self, _button: Gtk.Button) -> None:
        self._start_install("suggested")

    def _start_install(self, selection: str) -> None:
        if self.running:
            return
        self.model = ProgressModel()
        selected = self.catalog.suggested() if selection == "suggested" else [self.catalog.get(selection)]
        for app in selected:
            if app.key in self.rows:
                self.rows[app.key].status.set_text("Waiting")
        self.details.get_buffer().set_text("")
        self.status.set_text("Preparing the selected applications…")
        self._set_running(True)
        threading.Thread(target=self._install_worker, args=(selection,), daemon=True).start()

    @staticmethod
    def _installer_command() -> str:
        configured = os.environ.get("SPACED_WELCOME_INSTALLER")
        if configured:
            return configured
        installed = Path("/usr/bin/spaced-welcome-install")
        if installed.is_file():
            return str(installed)
        return str(Path(__file__).resolve().parents[2] / "bin" / "spaced-welcome-install")

    def _install_worker(self, selection: str) -> None:
        command = [self._installer_command(), "--install", selection, "--events"]
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        try:
            self.install_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=environment,
            )
            assert self.install_process.stdout is not None
            for raw_line in self.install_process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError
                except (json.JSONDecodeError, ValueError):
                    event = {"event": "detail", "message": line}
                GLib.idle_add(self._apply_event, event)
            returncode = self.install_process.wait()
        except OSError as error:
            GLib.idle_add(
                self._apply_event,
                {"event": "fatal", "message": f"Could not start the installer: {error}"},
            )
            returncode = 2
        finally:
            self.install_process = None
        GLib.idle_add(self._install_finished, returncode)

    def _apply_event(self, event: dict[str, Any]) -> bool:
        old_detail_count = len(self.model.details)
        self.model.apply(event)
        for line in self.model.details[old_detail_count:]:
            self._append_detail(line)
        app_key = str(event.get("app", ""))
        if app_key in self.rows and app_key in self.model.rows:
            self.rows[app_key].status.set_text(self.model.rows[app_key])
        self.status.set_text(self.model.summary)
        if event.get("event") in {"app-failure", "fatal"}:
            self.details_expander.set_expanded(True)
        return False

    def _install_finished(self, returncode: int) -> bool:
        self._set_running(False)
        pending = self.pending_bazaar
        self.pending_bazaar = None
        if returncode == 0 and pending is not None:
            self._launch_bazaar(pending[0], install_missing=False)
        if returncode != 0 and not self.model.summary.lower().startswith("installed"):
            self.status.set_text("Some applications failed. Open Details for the exact error.")
            self.details_expander.set_expanded(True)
        return False

    def _open_bazaar(self, _button: Gtk.Button) -> None:
        self._launch_bazaar()

    def _open_suggestion(
        self, _button: Gtk.Button, suggestion: AppSuggestion
    ) -> None:
        self._launch_bazaar(suggestion)

    def _launch_bazaar(
        self, suggestion: AppSuggestion | None = None, *, install_missing: bool = True
    ) -> None:
        if self.running:
            self.status.set_text("Please wait for the current installation to finish.")
            return
        self._set_running(True)
        self.status.set_text("Checking SpacedBazaar…")
        threading.Thread(
            target=self._check_bazaar, args=(suggestion, install_missing), daemon=True
        ).start()

    def _check_bazaar(self, suggestion: AppSuggestion | None, install_missing: bool) -> None:
        flatpak = os.environ.get("SPACED_WELCOME_FLATPAK", "/usr/bin/flatpak")
        try:
            check = subprocess.run(
                [flatpak, "info", BAZAAR_APP_ID],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            GLib.idle_add(self._bazaar_checked, suggestion, install_missing, False, str(error))
        else:
            GLib.idle_add(
                self._bazaar_checked, suggestion, install_missing, check.returncode == 0, None
            )

    def _bazaar_checked(
        self, suggestion: AppSuggestion | None, install_missing: bool,
        installed: bool, error: str | None,
    ) -> bool:
        self._set_running(False)
        if error is not None:
            self.status.set_text(f"Could not check SpacedBazaar: {error}")
            return False
        if not installed:
            if install_missing:
                self.pending_bazaar = (suggestion,)
                self.pages.set_visible_child_name("setup")
                self._start_install("spacedbazaar")
                return False
            message = "SpacedBazaar installation finished, but the app is still unavailable. Open Details."
            self.status.set_text(message)
            self._append_detail(message)
            self.details_expander.set_expanded(True)
            return False
        if suggestion is None:
            message = "Opening SpacedBazaar…"
        else:
            message = f"Opening {suggestion.app_name} in SpacedBazaar…"
        self.status.set_text(message)
        flatpak = os.environ.get("SPACED_WELCOME_FLATPAK", "/usr/bin/flatpak")
        try:
            subprocess.Popen(
                bazaar_command(flatpak, suggestion),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            self.status.set_text(f"Could not open SpacedBazaar: {error}")
        return False

    def _open_nvidia_installer(self, _button: Gtk.Button) -> None:
        command = os.environ.get("SPACED_WELCOME_NVIDIA_INSTALLER", "spaced-nvidia-installer")
        try:
            subprocess.Popen([command], start_new_session=True)
        except OSError as error:
            self.status.set_text(f"Could not open NVIDIA setup: {error}")

    def _on_destroy(self, _window: Gtk.Window) -> None:
        if self.install_process is not None and self.install_process.poll() is None:
            self.install_process.terminate()
        Gtk.main_quit()


def _state_file() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "spaced-linux/welcome-shown"


def _is_live_session() -> bool:
    return Path("/run/live/medium").exists() or Path("/lib/live/mount/medium").exists()


def _mark_shown() -> bool:
    state_file = _state_file()
    state_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_file.touch(mode=0o600, exist_ok=True)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spaced-welcome")
    parser.add_argument("--first-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--page", choices=("setup", "help"), default="setup",
                        help="open the setup or Help & Apps page")
    args = parser.parse_args(argv)
    if args.first_run and (_is_live_session() or _state_file().exists()):
        return 0
    try:
        window = WelcomeWindow()
    except CatalogError as error:
        print(f"spaced-welcome: {error}", file=sys.stderr)
        return 1
    window.show_all()
    window.pages.set_visible_child_name(args.page)
    window.spinner.hide()
    if args.first_run:
        GLib.idle_add(_mark_shown)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
