# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise UI action routing without requiring a display server."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from spaced_welcome.catalog import SOURCE_ROOT_CATALOG, load_catalog
from spaced_welcome.help import SUGGESTIONS
from spaced_welcome.progress import ProgressModel


spec = importlib.util.spec_from_file_location(
    "spaced_welcome._ui_actions_test",
    Path(__file__).parents[1] / "src/spaced_welcome/ui.py",
)
ui = importlib.util.module_from_spec(spec)
gtk = types.SimpleNamespace(Box=object, Window=object, main=MagicMock(), main_quit=MagicMock())
glib = types.SimpleNamespace(idle_add=MagicMock())
gi = types.SimpleNamespace(require_version=lambda *_args: None)
gio = types.SimpleNamespace(AppInfo=MagicMock())
repository = types.SimpleNamespace(Gtk=gtk, GLib=glib, Gio=gio)
with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
    spec.loader.exec_module(ui)


class UiActionTests(unittest.TestCase):
    def test_spacedbazaar_action_says_install_until_it_is_installed(self):
        window = MagicMock()
        window._flatpak_installed.return_value = False
        self.assertEqual(ui.WelcomeWindow._bazaar_heading(window),
                         "Install SpacedBazaar and then pick your own apps.")
        window._flatpak_installed.return_value = True
        self.assertEqual(ui.WelcomeWindow._bazaar_heading(window),
                         "Open SpacedBazaar and pick your own apps.")
        window._flatpak_installed.assert_called_with(ui.BAZAAR_APP_ID)

    def window(self):
        window = MagicMock()
        window.running = False
        window.catalog = load_catalog(SOURCE_ROOT_CATALOG)
        window.model = ProgressModel()
        window.pending_bazaar = None
        window.pending_link = None
        window.rows = {app.key: MagicMock() for app in window.catalog.suggested()}
        return window

    def test_missing_bazaar_installs_only_bazaar_and_preserves_app_page(self):
        window = self.window()
        suggestion = SUGGESTIONS[0]
        ui.WelcomeWindow._bazaar_checked(window, suggestion, True, False, None)
        window._start_install.assert_called_once_with("spacedbazaar")
        self.assertEqual(window.pending_bazaar, (suggestion,))
        window.pages.set_visible_child_name.assert_called_once_with("setup")

    def test_app_install_buttons_follow_the_running_state(self):
        window = self.window()
        ui.WelcomeWindow._set_running(window, True)
        for row in window.rows.values():
            row.install_button.set_sensitive.assert_called_with(False)
        ui.WelcomeWindow._set_running(window, False)
        for row in window.rows.values():
            row.install_button.set_sensitive.assert_called_with(True)

    def test_text_editor_is_not_a_browser(self):
        editor = MagicMock()
        editor.get_supported_types.return_value = ["text/plain"]
        with patch.object(ui.Gio.AppInfo, "get_default_for_uri_scheme", return_value=editor):
            self.assertFalse(ui.WelcomeWindow._has_browser())
        browser = MagicMock()
        browser.get_supported_types.return_value = ["text/html", "x-scheme-handler/https"]
        with patch.object(ui.Gio.AppInfo, "get_default_for_uri_scheme", return_value=browser):
            self.assertTrue(ui.WelcomeWindow._has_browser())
        with patch.object(ui.Gio.AppInfo, "get_default_for_uri_scheme", return_value=None):
            self.assertFalse(ui.WelcomeWindow._has_browser())

    def dialog_answering(self, response):
        dialog = MagicMock()
        dialog.run.return_value = response
        return patch.multiple(
            ui.Gtk, create=True,
            MessageDialog=MagicMock(return_value=dialog),
            MessageType=types.SimpleNamespace(QUESTION=1),
            ButtonsType=types.SimpleNamespace(NONE=0),
            ResponseType=types.SimpleNamespace(ACCEPT=-3, CANCEL=-6),
        )

    def test_link_without_browser_offers_brave_then_opens_the_page(self):
        window = self.window()
        window._has_browser.return_value = False
        with self.dialog_answering(-3):
            self.assertTrue(ui.WelcomeWindow._open_link(window, "https://spacedlinux.com"))
        window._start_install.assert_called_once_with("brave")
        self.assertEqual(window.pending_link, "https://spacedlinux.com")
        ui.WelcomeWindow._install_finished(window, 0)
        window._open_in_browser.assert_called_once_with("https://spacedlinux.com")
        self.assertIsNone(window.pending_link)

    def test_declined_browser_install_opens_nothing(self):
        window = self.window()
        window._has_browser.return_value = False
        with self.dialog_answering(-6):
            ui.WelcomeWindow._open_link(window, "https://spacedlinux.com")
        window._start_install.assert_not_called()
        self.assertIsNone(window.pending_link)

    def test_failed_browser_install_does_not_open_the_page(self):
        window = self.window()
        window.pending_link = "https://spacedlinux.com"
        ui.WelcomeWindow._install_finished(window, 1)
        window._open_in_browser.assert_not_called()

    def test_link_with_browser_opens_directly(self):
        window = self.window()
        window._has_browser.return_value = True
        with patch.multiple(ui.Gtk, create=True, show_uri_on_window=MagicMock(),
                            get_current_event_time=MagicMock(return_value=0)):
            ui.WelcomeWindow._open_link(window, "https://spacedlinux.com")
            ui.Gtk.show_uri_on_window.assert_called_once_with(window, "https://spacedlinux.com", 0)
        window._start_install.assert_not_called()

    def test_browser_opens_through_its_catalog_flatpak(self):
        window = self.window()
        with patch.object(ui.subprocess, "Popen") as popen:
            ui.WelcomeWindow._open_in_browser(window, "https://spacedlinux.com")
        self.assertEqual(popen.call_args.args[0],
                         ["flatpak", "run", "com.brave.Browser", "https://spacedlinux.com"])

    def test_success_launches_pending_bazaar_without_reinstall_loop(self):
        window = self.window()
        window.pending_bazaar = (SUGGESTIONS[0],)
        ui.WelcomeWindow._install_finished(window, 0)
        window._launch_bazaar.assert_called_once_with(SUGGESTIONS[0], install_missing=False)
        self.assertIsNone(window.pending_bazaar)

    def test_failed_install_does_not_launch_or_retry_bazaar(self):
        window = self.window()
        window.pending_bazaar = (None,)
        ui.WelcomeWindow._install_finished(window, 1)
        window._launch_bazaar.assert_not_called()
        self.assertIsNone(window.pending_bazaar)

    def test_post_install_missing_app_does_not_loop(self):
        window = self.window()
        ui.WelcomeWindow._bazaar_checked(window, None, False, False, None)
        window._start_install.assert_not_called()
        self.assertIn("still unavailable", window.status.set_text.call_args.args[0])

    def test_start_install_marks_only_selected_app_and_passes_selection(self):
        window = self.window()
        with patch.object(ui.threading, "Thread") as thread:
            ui.WelcomeWindow._start_install(window, "spacedbazaar")
        thread.assert_called_once_with(
            target=window._install_worker, args=("spacedbazaar",), daemon=True
        )
        window.rows["spacedbazaar"].status.set_text.assert_called_once_with("Waiting")
        window.rows["voxa"].status.set_text.assert_not_called()
        window._set_running.assert_called_once_with(True)

    def test_running_guard_prevents_duplicate_install_workers(self):
        window = self.window()
        window.running = True
        with patch.object(ui.threading, "Thread") as thread:
            ui.WelcomeWindow._start_install(window, "spacedbazaar")
        thread.assert_not_called()

    def test_existing_bazaar_opens_requested_page_without_install(self):
        window = self.window()
        with patch.object(ui.subprocess, "Popen") as process:
            ui.WelcomeWindow._bazaar_checked(window, SUGGESTIONS[0], True, True, None)
        self.assertEqual(process.call_args.args[0][-1], SUGGESTIONS[0].uri)
        window._start_install.assert_not_called()

    def test_help_page_cli_opens_help_and_apps(self):
        window = self.window()
        with patch.object(ui, "WelcomeWindow", return_value=window):
            self.assertEqual(ui.main(["--page", "help"]), 0)
        window.pages.set_visible_child_name.assert_called_once_with("help")

    def test_busy_close_keeps_installer_running(self):
        window = self.window()
        window.running = True
        self.assertTrue(ui.WelcomeWindow._on_delete(window))
        self.assertIn("finish before closing", window.status.set_text.call_args.args[0])
        window.install_process.terminate.assert_not_called()
        window.destroy.assert_not_called()
        window.running = False
        self.assertFalse(ui.WelcomeWindow._on_delete(window))

    def test_forced_destroy_reaps_owned_installer_group(self):
        window = self.window()
        window.install_process.poll.return_value = None
        window.install_process.pid = 12345
        with patch.object(ui.os, "killpg") as kill:
            ui.WelcomeWindow._on_destroy(window, window)
        kill.assert_called_once_with(12345, ui.signal.SIGTERM)
        window.install_process.wait.assert_called_once_with(timeout=5)

    def test_installer_has_its_own_process_group(self):
        window = self.window()
        window._installer_command.return_value = "spaced-welcome-install"
        process = MagicMock()
        process.stdout = iter([])
        process.wait.return_value = 0
        with patch.object(ui.subprocess, "Popen", return_value=process) as popen:
            ui.WelcomeWindow._install_worker(window, "suggested")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIsNone(window.install_process)

    def test_warning_text_is_exact(self):
        source = (Path(__file__).parents[1] / "src/spaced_welcome/ui.py").read_text()
        self.assertIn("IF YOU CLOSE THIS APP WITHOUT INSTALLING ANYTHING:", source)
        self.assertIn("YOU WILL NOT HAVE A BROWSER OR BE ABLE TO PLAY MEDIA FILES.", source)

    def test_warning_hidden_when_browser_and_media_player_installed(self):
        window = self.window()
        with patch.object(ui.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)):
            self.assertTrue(ui.WelcomeWindow._warning_hidden(window))

    def test_warning_shown_when_media_player_missing(self):
        window = self.window()

        def check(command, **_kwargs):
            return types.SimpleNamespace(returncode=0 if command[-1] == "com.brave.Browser" else 1)

        with patch.object(ui.subprocess, "run", side_effect=check):
            self.assertFalse(ui.WelcomeWindow._warning_hidden(window))

    def test_warning_shown_when_installed_apps_cannot_be_known(self):
        window = self.window()
        with patch.object(ui.subprocess, "run", side_effect=FileNotFoundError):
            self.assertFalse(ui.WelcomeWindow._warning_hidden(window))

    def test_suggested_row_opens_an_installed_app_and_installs_a_missing_one(self):
        window = self.window()
        app = window.catalog.suggested()[0]
        window._flatpak_installed.return_value = True
        with patch.object(ui.subprocess, "Popen") as popen:
            ui.WelcomeWindow._open_or_install(window, app.key)
        self.assertEqual(popen.call_args.args[0][1:], ["run", app.app_id])
        window._start_install.assert_not_called()
        window._flatpak_installed.return_value = False
        with patch.object(ui.subprocess, "Popen") as popen:
            ui.WelcomeWindow._open_or_install(window, app.key)
        popen.assert_not_called()
        window._start_install.assert_called_once_with(app.key)

    def test_help_button_label_says_open_when_app_installed(self):
        window = self.window()
        window._flatpak_installed.return_value = True
        suggestion = SUGGESTIONS[0]
        self.assertEqual(
            ui.WelcomeWindow._suggestion_label(window, suggestion),
            f"Open {suggestion.app_name}",
        )

    def test_help_button_label_says_install_when_app_missing(self):
        window = self.window()
        window._flatpak_installed.return_value = False
        suggestion = SUGGESTIONS[0]
        self.assertEqual(
            ui.WelcomeWindow._suggestion_label(window, suggestion),
            f"Install {suggestion.app_name}",
        )

    def test_open_button_launches_installed_app_without_bazaar(self):
        window = self.window()
        suggestion = SUGGESTIONS[0]
        with patch.object(ui.subprocess, "Popen") as process:
            ui.WelcomeWindow._suggestion_checked(window, suggestion, True, None)
        self.assertEqual(process.call_args.args[0], ["/usr/bin/flatpak", "run", suggestion.app_id])
        window._start_install.assert_not_called()
        window.bazaar_confirm.set_visible.assert_not_called()

    def test_install_button_with_bazaar_present_opens_app_page_without_install(self):
        window = self.window()
        suggestion = SUGGESTIONS[0]
        with patch.object(ui.subprocess, "Popen") as process:
            ui.WelcomeWindow._suggestion_checked(window, suggestion, False, True)
        self.assertEqual(process.call_args.args[0][-1], suggestion.uri)
        window._start_install.assert_not_called()
        window.bazaar_confirm.set_visible.assert_not_called()

    def test_install_button_with_bazaar_missing_asks_confirmation_without_installing(self):
        window = self.window()
        suggestion = SUGGESTIONS[0]
        ui.WelcomeWindow._suggestion_checked(window, suggestion, False, False)
        self.assertEqual(window.pending_confirm, (suggestion,))
        window.bazaar_confirm.set_visible.assert_called_once_with(True)
        window._start_install.assert_not_called()

    def test_cancel_confirmation_installs_nothing_and_hides_panel(self):
        window = self.window()
        window.pending_confirm = (SUGGESTIONS[0],)
        ui.WelcomeWindow._cancel_bazaar_install(window, MagicMock())
        window.bazaar_confirm.set_visible.assert_called_once_with(False)
        self.assertIsNone(window.pending_confirm)
        window._start_install.assert_not_called()
        window.pages.set_visible_child_name.assert_not_called()

    def test_confirm_confirmation_installs_bazaar_and_opens_app_page(self):
        window = self.window()
        suggestion = SUGGESTIONS[0]
        window.pending_confirm = (suggestion,)
        ui.WelcomeWindow._confirm_bazaar_install(window, MagicMock())
        window._start_install.assert_called_once_with("spacedbazaar")
        self.assertEqual(window.pending_bazaar, (suggestion,))
        window.pages.set_visible_child_name.assert_called_once_with("setup")
        window.bazaar_confirm.set_visible.assert_called_once_with(False)
        self.assertIsNone(window.pending_confirm)


if __name__ == "__main__":
    unittest.main()
