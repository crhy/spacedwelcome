# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise AI Setup page action routing without requiring a display server."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from spaced_welcome.ai_setup import AiSetupModel


spec = importlib.util.spec_from_file_location(
    "spaced_welcome._ai_setup_ui_actions_test",
    Path(__file__).parents[1] / "src/spaced_welcome/ui.py",
)
ui = importlib.util.module_from_spec(spec)
gtk = types.SimpleNamespace(
    Box=object, Window=object, Label=MagicMock(), main=MagicMock(), main_quit=MagicMock()
)
glib = types.SimpleNamespace(idle_add=MagicMock())
gi = types.SimpleNamespace(require_version=lambda *_args: None)
repository = types.SimpleNamespace(Gtk=gtk, GLib=glib)
with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
    spec.loader.exec_module(ui)


class AiSetupUiActionTests(unittest.TestCase):
    def window(self):
        window = MagicMock()
        window.ai_running = False
        window.ai_model = AiSetupModel()
        window.ai_buttons = [MagicMock(), MagicMock()]
        window.recommended_model = None
        window.peripherals_box.get_children.return_value = []
        window.printers_box.get_children.return_value = []
        return window

    def test_hardware_check_starts_a_recommend_model_task(self):
        window = self.window()
        ui.WelcomeWindow._check_hardware(window, MagicMock())
        args = window._start_ai_task.call_args.args[0]
        self.assertEqual(args, ["--recommend-model", "--json"])

    def test_successful_hardware_check_enables_install_and_stores_model(self):
        window = self.window()
        ui.WelcomeWindow._check_hardware(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(0, {"model": "qwen2:7b", "reason": "balanced", "ram_gb": 16.0, "gpu_name": None})
        self.assertEqual(window.recommended_model, "qwen2:7b")
        window.install_model_button.set_sensitive.assert_called_once_with(True)
        self.assertIn("qwen2:7b", window.ai_status.set_text.call_args.args[0])

    def test_failed_hardware_check_does_not_enable_install(self):
        window = self.window()
        ui.WelcomeWindow._check_hardware(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(1, None)
        self.assertIsNone(window.recommended_model)
        window.install_model_button.set_sensitive.assert_not_called()

    def test_install_recommended_model_is_a_noop_without_a_recommendation(self):
        window = self.window()
        window.recommended_model = None
        ui.WelcomeWindow._install_recommended_model(window, MagicMock())
        window._start_ai_task.assert_not_called()

    def test_install_recommended_model_streams_events(self):
        window = self.window()
        window.recommended_model = "qwen2:7b"
        ui.WelcomeWindow._install_recommended_model(window, MagicMock())
        window._start_ai_task.assert_called_once_with(["--install-model", "qwen2:7b", "--events"])

    def test_peripherals_result_renders_each_row(self):
        window = self.window()
        ui.WelcomeWindow._check_peripherals(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(
            0,
            [
                {"name": "Webcam", "present": True, "detail": "detected (video0)"},
                {"name": "Battery", "present": False, "detail": "not detected"},
            ],
        )
        self.assertEqual(window.peripherals_box.pack_start.call_count, 2)
        window.peripherals_box.show_all.assert_called_once()

    def test_peripherals_failure_clears_without_new_rows(self):
        window = self.window()
        window.peripherals_box.get_children.return_value = [MagicMock()]
        ui.WelcomeWindow._check_peripherals(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(2, None)
        window.peripherals_box.remove.assert_called_once()
        window.peripherals_box.pack_start.assert_not_called()

    def test_printers_found_are_listed(self):
        window = self.window()
        ui.WelcomeWindow._find_printers(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(0, [{"uri": "dnssd://Office/", "make_and_model": "Office"}])
        window.printers_box.pack_start.assert_called_once()
        window.printers_box.show_all.assert_called_once()

    def test_no_printers_found_adds_no_rows(self):
        # The status line already says so; a row here would repeat it verbatim.
        window = self.window()
        ui.WelcomeWindow._find_printers(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(0, [])
        window.printers_box.pack_start.assert_not_called()

    def test_running_guard_prevents_duplicate_ai_tasks(self):
        window = self.window()
        window.ai_running = True
        with patch.object(ui.threading, "Thread") as thread:
            ui.WelcomeWindow._start_ai_task(window, ["--check-peripherals"])
        thread.assert_not_called()

    def test_start_ai_task_launches_a_worker_thread(self):
        window = self.window()
        with patch.object(ui.threading, "Thread") as thread:
            ui.WelcomeWindow._start_ai_task(window, ["--check-peripherals", "--json"])
        thread.assert_called_once()
        self.assertEqual(
            thread.call_args.kwargs["args"], (["--check-peripherals", "--json"], None)
        )
        window._set_ai_running.assert_called_once_with(True)

    def test_apply_event_updates_status_and_details(self):
        window = self.window()
        ui.WelcomeWindow._apply_ai_event(window, {"event": "detail", "message": "Recording…"})
        window._append_ai_detail.assert_called_once_with("Recording…")
        self.assertEqual(window.ai_model.summary, "Recording…")

    def test_task_failure_expands_details(self):
        window = self.window()
        ui.WelcomeWindow._apply_ai_event(window, {"event": "task-failure", "message": "No signal"})
        window.ai_details_expander.set_expanded.assert_called_once_with(True)

    def test_open_sound_settings_reports_failure(self):
        window = self.window()
        ui.WelcomeWindow._open_sound_settings(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(2, None)
        self.assertIn("Sound Settings", window.ai_status.set_text.call_args.args[0])

    def test_open_printer_settings_reports_failure(self):
        window = self.window()
        ui.WelcomeWindow._open_printer_settings(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(2, None)
        self.assertIn("Printer Settings", window.ai_status.set_text.call_args.args[0])

    def test_open_sound_settings_confirms_success(self):
        window = self.window()
        ui.WelcomeWindow._open_sound_settings(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(0, None)
        self.assertEqual(window.ai_status.set_text.call_args.args[0], "Opened Sound Settings.")

    def test_eventless_task_does_not_leave_the_status_working(self):
        window = self.window()
        ui.WelcomeWindow._ai_task_finished(window, 0, None, None)
        self.assertEqual(window.ai_status.set_text.call_args.args[0], "Done")

    def test_eventless_failure_is_reported(self):
        window = self.window()
        ui.WelcomeWindow._ai_task_finished(window, 1, None, None)
        self.assertEqual(window.ai_status.set_text.call_args.args[0], "That did not work")

    def test_a_task_that_reported_progress_keeps_its_last_message(self):
        window = self.window()
        window.ai_model.apply({"event": "task-success", "message": "Microphone is working"})
        ui.WelcomeWindow._ai_task_finished(window, 0, None, None)
        window.ai_status.set_text.assert_not_called()

    def test_peripherals_result_summarises_what_was_detected(self):
        window = self.window()
        ui.WelcomeWindow._check_peripherals(window, MagicMock())
        on_result = window._start_ai_task.call_args.args[1]
        on_result(0, [{"name": "Webcam", "detail": "d", "present": True},
                      {"name": "Battery", "detail": "n", "present": False}])
        self.assertEqual(
            window.ai_status.set_text.call_args.args[0],
            "Checked 2 peripherals, 1 detected",
        )


if __name__ == "__main__":
    unittest.main()
