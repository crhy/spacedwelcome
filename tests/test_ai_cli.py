# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from spaced_welcome.ai_setup import MODEL_CATALOG


ROOT = Path(__file__).resolve().parents[1]


class AiSetupCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.fake_bin = self.work / "bin"
        self.fake_bin.mkdir()
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PYTHONPATH": str(ROOT / "src"),
                "PATH": str(self.fake_bin),
                "SPACED_WELCOME_MEMINFO": str(self.work / "meminfo"),
                "SPACED_WELCOME_NVIDIA_SMI": "nvidia-smi-absent",
                "SPACED_WELCOME_DEV_ROOT": str(self.work / "dev"),
                "SPACED_WELCOME_SYS_ROOT": str(self.work / "sys"),
            }
        )
        (self.work / "meminfo").write_text("MemTotal:       8000000 kB\n")
        (self.work / "dev").mkdir()
        (self.work / "sys/class/bluetooth").mkdir(parents=True)
        (self.work / "sys/class/power_supply").mkdir(parents=True)
        (self.work / "sys/class/net").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _executable(path: Path, source: str):
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(0o755)

    def run_cli(self, *args: str, extra_env: dict[str, str] | None = None):
        environment = self.environment.copy()
        if extra_env:
            environment.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "spaced_welcome.ai_cli", *args],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_detect_hardware_reports_ram_as_json(self):
        result = self.run_cli("--detect-hardware", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ram_gb"], 7.6)
        self.assertIsNone(payload["gpu_name"])

    def test_recommend_model_prints_a_model_name(self):
        result = self.run_cli("--recommend-model")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        named = [tier.name for tier in MODEL_CATALOG if result.stdout.startswith(tier.name)]
        self.assertEqual(len(named), 1, f"no catalog model named in {result.stdout!r}")

    def test_recommend_model_json_includes_hardware(self):
        result = self.run_cli("--recommend-model", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["ram_gb"], 7.6)
        self.assertIn("model", payload)
        self.assertIn("reason", payload)

    def test_check_peripherals_emits_json_rows(self):
        result = self.run_cli("--check-peripherals", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual({row["name"] for row in rows}, {"Webcam", "Bluetooth", "Battery", "Wi-Fi"})

    def test_install_model_streams_events_and_fails_without_ollama(self):
        result = self.run_cli(
            "--install-model", "qwen2:0.5b", "--events", extra_env={"SPACED_WELCOME_OLLAMA": "ollama-absent"}
        )
        self.assertEqual(result.returncode, 1)
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(any(event["event"] == "task-failure" for event in events))
        self.assertIn("ollama.com/install.sh", events[-1]["message"])

    def test_find_printers_reports_discovered_devices(self):
        self._executable(
            self.fake_bin / "lpinfo",
            r"""
            #!/usr/bin/python3
            print("network dnssd://Kitchen%20Printer._ipp._tcp.local/")
            """,
        )
        result = self.run_cli("--find-printers", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        printers = json.loads(result.stdout)
        self.assertEqual(len(printers), 1)
        self.assertIn("Kitchen", printers[0]["uri"])

    def test_open_sound_settings_reports_missing_command(self):
        result = self.run_cli(
            "--open-sound-settings",
            extra_env={"SPACED_WELCOME_SOUND_SETTINGS": "sound-settings-absent"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Could not open Sound Settings", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
