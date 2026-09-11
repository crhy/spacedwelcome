# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import textwrap
import unittest

from spaced_welcome.ai_setup import (
    AiSetup,
    clean_progress_line,
    HardwareProfile,
    MODEL_CATALOG,
    _detect_gpu,
    _read_ram_gb,
    recommend_model,
)


class HardwareDetectionTests(unittest.TestCase):
    def test_ram_is_read_from_meminfo_in_gb(self):
        with tempfile.TemporaryDirectory() as work:
            meminfo = Path(work) / "meminfo"
            meminfo.write_text("MemTotal:       16384000 kB\nMemFree: 100 kB\n")
            self.assertEqual(_read_ram_gb(meminfo), 15.6)

    def test_missing_meminfo_reads_as_zero(self):
        self.assertEqual(_read_ram_gb("/nonexistent/meminfo"), 0.0)

    def test_gpu_is_none_when_nvidia_smi_is_absent(self):
        name, vram = _detect_gpu("nvidia-smi-does-not-exist")
        self.assertIsNone(name)
        self.assertEqual(vram, 0.0)


class ModelRecommendationTests(unittest.TestCase):
    def test_minimal_hardware_gets_the_smallest_model(self):
        profile = HardwareProfile(ram_gb=2.0, gpu_name=None, gpu_vram_gb=0.0)
        self.assertEqual(recommend_model(profile).model, MODEL_CATALOG[0].name)

    def test_desktop_ram_gets_the_balanced_model(self):
        profile = HardwareProfile(ram_gb=16.0, gpu_name=None, gpu_vram_gb=0.0)
        self.assertEqual(recommend_model(profile).model, "qwen2.5:14b")

    def test_large_gpu_gets_the_best_model_regardless_of_ram(self):
        profile = HardwareProfile(ram_gb=8.0, gpu_name="RTX 4090", gpu_vram_gb=24.0)
        self.assertEqual(recommend_model(profile).model, "qwen2.5:14b")

    def test_small_gpu_does_not_get_the_best_model_even_with_lots_of_ram(self):
        profile = HardwareProfile(ram_gb=64.0, gpu_name="GTX 1650", gpu_vram_gb=4.0)
        self.assertEqual(recommend_model(profile).model, "llama3.2:3b")

    def test_a_16gb_card_is_offered_more_than_a_7b_model(self):
        # The old flat tiers gave every card from 8GB to 17GB the same 7b
        # model, which used under a third of a 16GB card.
        profile = HardwareProfile(ram_gb=32.0, gpu_name="RTX 4070 Ti SUPER", gpu_vram_gb=16.0)
        self.assertEqual(recommend_model(profile).model, "qwen2.5:14b")

    def test_headroom_rejects_a_model_that_only_fits_by_its_weights(self):
        # qwen2.5:14b is 9GB of weights, so it "fits" 10GB on paper; the cache
        # and activations do not, and the rule has to say no.
        profile = HardwareProfile(ram_gb=8.0, gpu_name="RTX 3080", gpu_vram_gb=10.0)
        self.assertEqual(recommend_model(profile).model, "llama3.1:8b")

    def test_every_catalog_entry_is_reachable_by_some_machine(self):
        for tier in MODEL_CATALOG:
            budget = tier.approx_gb * 1.3 + 1.0
            profile = HardwareProfile(ram_gb=budget, gpu_name=None, gpu_vram_gb=0.0)
            self.assertEqual(recommend_model(profile).model, tier.name)


class PeripheralCheckTests(unittest.TestCase):
    def test_present_and_missing_devices_are_reported(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "dev").mkdir()
            (root / "dev/video0").touch()
            (root / "sys/class/bluetooth").mkdir(parents=True)
            (root / "sys/class/power_supply").mkdir(parents=True)
            (root / "sys/class/net").mkdir(parents=True)
            setup = AiSetup()
            setup.dev_root = root / "dev"
            setup.sys_root = root / "sys"
            checks = {check.name: check for check in setup.check_peripherals()}
            self.assertTrue(checks["Webcam"].present)
            self.assertFalse(checks["Bluetooth"].present)
            self.assertFalse(checks["Battery"].present)
            self.assertFalse(checks["Wi-Fi"].present)

    def test_missing_roots_do_not_raise(self):
        setup = AiSetup()
        setup.dev_root = Path("/nonexistent/dev")
        setup.sys_root = Path("/nonexistent/sys")
        checks = setup.check_peripherals()
        self.assertTrue(all(not check.present for check in checks))


class SubprocessHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.fake_bin = self.work / "bin"
        self.fake_bin.mkdir()
        self.original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.fake_bin}:{self.original_path}"

    def tearDown(self):
        os.environ["PATH"] = self.original_path
        self.temp.cleanup()

    @staticmethod
    def _executable(path: Path, source: str):
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(0o755)

    def test_microphone_reports_the_peak_level_of_a_real_signal(self):
        self._executable(
            self.fake_bin / "arecord",
            r"""
            #!/usr/bin/python3
            import sys, wave
            args = sys.argv[1:]
            path = args[-1]
            with wave.open(path, 'wb') as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes((20000).to_bytes(2, 'little', signed=True) * 100)
            """,
        )
        events = []
        setup = AiSetup(callback=events.append)
        result = setup.test_microphone(seconds=1)
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.peak_level, 20000 / 32768, places=3)
        self.assertTrue(any(event["event"] == "task-success" for event in events))

    def test_microphone_reports_silence(self):
        self._executable(
            self.fake_bin / "arecord",
            r"""
            #!/usr/bin/python3
            import sys, wave
            path = sys.argv[-1]
            with wave.open(path, 'wb') as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes((0).to_bytes(2, 'little', signed=True) * 100)
            """,
        )
        setup = AiSetup()
        result = setup.test_microphone(seconds=1)
        self.assertFalse(result.ok)
        self.assertIn("No signal", result.message)

    def test_microphone_is_reported_missing_without_any_recorder(self):
        setup = AiSetup()
        setup.arecord = "arecord-does-not-exist"
        setup.parecord = "parecord-does-not-exist"
        result = setup.test_microphone(seconds=1)
        self.assertFalse(result.ok)
        self.assertIn("Neither arecord nor parecord is installed", result.message)

    def test_microphone_falls_back_to_parecord_without_arecord(self):
        self._executable(
            self.fake_bin / "parecord",
            r"""
            #!/usr/bin/python3
            import sys, time, wave
            path = sys.argv[-1]
            with wave.open(path, 'wb') as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes((18000).to_bytes(2, 'little', signed=True) * 100)
            # parecord has no duration flag; it runs until it is stopped.
            time.sleep(30)
            """,
        )
        setup = AiSetup()
        setup.arecord = "arecord-does-not-exist"
        result = setup.test_microphone(seconds=1)
        self.assertTrue(result.ok, result.message)
        self.assertAlmostEqual(result.peak_level, 18000 / 32768, places=3)

    def test_microphone_reports_parecord_exiting_early(self):
        self._executable(
            self.fake_bin / "parecord",
            r"""
            #!/bin/sh
            echo "connection refused" >&2
            exit 1
            """,
        )
        setup = AiSetup()
        setup.arecord = "arecord-does-not-exist"
        result = setup.test_microphone(seconds=1)
        self.assertFalse(result.ok)
        self.assertIn("connection refused", result.message)

    def test_progress_lines_lose_their_terminal_control_codes(self):
        raw = (
            "pulling c5396e06af29: 100% \u2595\u2588\u2588\u258f 396 MB/397 MB"
            "\x1b[K\x1b[?25h\x1b[?2026l\r"
        )
        self.assertEqual(
            clean_progress_line(raw),
            "pulling c5396e06af29: 100% \u2595\u2588\u2588\u258f 396 MB/397 MB",
        )

    def test_progress_line_of_only_control_codes_is_dropped(self):
        self.assertEqual(clean_progress_line("\x1b[?25l\x1b[A\x1b[1G\x1b[K"), "")

    def test_ollama_missing_reports_the_install_command(self):
        events = []
        setup = AiSetup(callback=events.append)
        setup.ollama = "ollama-does-not-exist"
        self.assertFalse(setup.install_model("qwen2:0.5b"))
        failure = next(event for event in events if event["event"] == "task-failure")
        self.assertIn("ollama.com/install.sh", failure["message"])

    def test_ollama_pull_success_streams_and_succeeds(self):
        self._executable(
            self.fake_bin / "ollama",
            r"""
            #!/usr/bin/python3
            print("pulling manifest")
            print("verifying sha256 digest")
            """,
        )
        events = []
        setup = AiSetup(callback=events.append)
        self.assertTrue(setup.install_model("qwen2:0.5b"))
        self.assertTrue(any(event["event"] == "task-success" for event in events))
        self.assertTrue(any("pulling manifest" in event.get("message", "") for event in events))

    def test_ollama_pull_failure_is_reported(self):
        self._executable(
            self.fake_bin / "ollama",
            r"""
            #!/usr/bin/python3
            import sys
            print("could not reach registry")
            sys.exit(1)
            """,
        )
        events = []
        setup = AiSetup(callback=events.append)
        self.assertFalse(setup.install_model("qwen2:0.5b"))
        self.assertTrue(any(event["event"] == "task-failure" for event in events))

    def test_find_printers_parses_network_backends_only(self):
        self._executable(
            self.fake_bin / "lpinfo",
            r"""
            #!/usr/bin/python3
            print("network dnssd://Office%20Printer._ipp._tcp.local/")
            print("network socket://192.168.1.50:9100")
            print("direct usb://Example/Printer?serial=123")
            """,
        )
        events = []
        setup = AiSetup(callback=events.append)
        printers = setup.find_printers()
        self.assertEqual(len(printers), 2)
        self.assertTrue(any(event["event"] == "task-success" for event in events))

    def test_find_printers_with_no_results_is_not_a_failure(self):
        self._executable(self.fake_bin / "lpinfo", "#!/usr/bin/python3\n")
        setup = AiSetup()
        self.assertEqual(setup.find_printers(), [])

    def test_find_printers_ignores_bare_backend_names(self):
        # What lpinfo -v actually prints on a machine with no printers at all.
        self._executable(
            self.fake_bin / "lpinfo",
            r"""
            #!/usr/bin/python3
            for line in ("file cups-brf:/", "network beh", "network https",
                         "network http", "network socket", "network lpd",
                         "network ipp", "network ipps"):
                print(line)
            """,
        )
        events = []
        setup = AiSetup(callback=events.append)
        self.assertEqual(setup.find_printers(), [])
        self.assertFalse(any(event["event"] == "task-success" for event in events))

    def test_find_printers_finds_lpinfo_in_sbin_off_the_user_path(self):
        sbin = Path(self.temp.name) / "sbin"
        sbin.mkdir()
        self._executable(
            sbin / "lpinfo",
            r"""
            #!/bin/sh
            echo "network socket://192.0.2.10"
            """,
        )
        setup = AiSetup()
        setup.sbin_path = str(sbin)
        printers = setup.find_printers()
        self.assertEqual([printer.uri for printer in printers], ["socket://192.0.2.10"])

    def test_find_printers_is_reported_missing_without_lpinfo(self):
        setup = AiSetup()
        setup.lpinfo = "lpinfo-does-not-exist"
        self.assertEqual(setup.find_printers(), [])


if __name__ == "__main__":
    unittest.main()
