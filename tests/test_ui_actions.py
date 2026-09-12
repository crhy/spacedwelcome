# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise UI action routing without requiring a display server."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from spaced_welcome.catalog import load_catalog
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
repository = types.SimpleNamespace(Gtk=gtk, GLib=glib)
with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
    spec.loader.exec_module(ui)


class UiActionTests(unittest.TestCase):
    def test_spacedbazaar_action_uses_clear_install_wording(self):
        source = (Path(__file__).parents[1] / "src/spaced_welcome/ui.py").read_text()
        self.assertIn("Install SpacedBazaar and then pick your own apps.", source)
        self.assertNotIn('"Open SpacedBazaar"', source)

    def window(self):
        window = MagicMock()
        window.running = False
        window.catalog = load_catalog()
        window.model = ProgressModel()
        window.pending_bazaar = None
        window.rows = {app.key: MagicMock() for app in window.catalog.suggested()}
        return window

    def test_missing_bazaar_installs_only_bazaar_and_preserves_app_page(self):
        window = self.window()
        suggestion = SUGGESTIONS[0]
        ui.WelcomeWindow._bazaar_checked(window, suggestion, True, False, None)
        window._start_install.assert_called_once_with("spacedbazaar")
        self.assertEqual(window.pending_bazaar, (suggestion,))
        window.pages.set_visible_child_name.assert_called_once_with("setup")

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
        window.rows["voice2text"].status.set_text.assert_not_called()
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


if __name__ == "__main__":
    unittest.main()
