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


ROOT = Path(__file__).resolve().parents[1]


class InstallerCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.fake_bin = self.work / "bin"
        self.fake_bin.mkdir()
        self.log = self.work / "commands.jsonl"
        self.counter = self.work / "install-count"
        self.marker = self.work / "installed"
        self.catalog = self.work / "catalog.json"
        self._write_catalog()
        self._write_fake_flatpak()
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PYTHONPATH": str(ROOT / "src"),
                "PATH": str(self.fake_bin),
                "SPACED_WELCOME_CATALOG": str(self.catalog),
                "SPACED_WELCOME_FLATPAK": str(self.fake_bin / "flatpak"),
                "SPACED_WELCOME_RETRY_DELAY": "0",
                "SPACED_WELCOME_ATTEMPTS": "3",
                "FAKE_LOG": str(self.log),
                "FAKE_COUNTER": str(self.counter),
                "FAKE_MARKER": str(self.marker),
                "FAKE_REMOTE_PRESENT": "1",
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def _write_catalog(self, *, preinstalled: bool = False, source: str = "spaced-github"):
        payload = {
            "schema_version": 1,
            "apps": [
                {
                    "key": "test-app",
                    "name": "Test App",
                    "app_id": "io.github.crhy.TestApp",
                    "branch": "master",
                    "description": "Test application",
                    "preinstalled": preinstalled,
                    "suggested": not preinstalled,
                    "source": {"type": source},
                }
            ],
        }
        self.catalog.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _executable(path: Path, source: str):
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(0o755)

    def _write_fake_flatpak(self):
        self._executable(
            self.fake_bin / "flatpak",
            r"""
            #!/usr/bin/python3
            import json, os, pathlib, sys
            args = sys.argv[1:]
            log = pathlib.Path(os.environ['FAKE_LOG'])
            with log.open('a', encoding='utf-8') as target:
                target.write(json.dumps(args) + '\n')
            command = args[0]
            if command == 'remotes':
                if os.environ.get('FAKE_REMOTE_PRESENT') == '1':
                    name = os.environ.get('FAKE_REMOTE_NAME', 'spaced-github')
                    default_url = {
                        'flathub': 'https://dl.flathub.org/repo/',
                        'spaced-github': 'https://crhy.github.io/spacedbazaar/flatpak-repo/',
                    }[name]
                    print(name + '\t' + os.environ.get('FAKE_REMOTE_URL', default_url))
                raise SystemExit(0)
            if command == 'remote-add':
                raise SystemExit(int(os.environ.get('FAKE_REMOTE_ADD_FAILURE', '0')))
            if command == 'install':
                counter = pathlib.Path(os.environ['FAKE_COUNTER'])
                count = int(counter.read_text() if counter.exists() else '0') + 1
                counter.write_text(str(count))
                print(f'Flatpak install attempt {count}')
                if count <= int(os.environ.get('FAKE_INSTALL_FAILURES', '0')):
                    raise SystemExit(1)
                pathlib.Path(os.environ['FAKE_MARKER']).touch()
                raise SystemExit(0)
            if command == 'info':
                installed = (
                    os.environ.get('FAKE_ALREADY_INSTALLED') == '1'
                    or os.environ.get('FAKE_PREINSTALLED') == '1'
                    or pathlib.Path(os.environ['FAKE_MARKER']).exists()
                )
                raise SystemExit(0 if installed else 1)
            raise SystemExit(0)
            """,
        )

    def run_cli(self, *args: str, extra_env: dict[str, str] | None = None):
        environment = self.environment.copy()
        if extra_env:
            environment.update(extra_env)
        return subprocess.run(
            [sys.executable, "-m", "spaced_welcome.cli", *args],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    @staticmethod
    def events(result: subprocess.CompletedProcess[str]):
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    def commands(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_first_party_app_installs_by_id_from_signed_remote(self):
        result = self.run_cli("--install", "test-app", "--events")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        install = [command for command in self.commands() if command[0] == "install"]
        self.assertEqual(len(install), 1)
        self.assertEqual(
            install[0][-2:], ["spaced-github", "io.github.crhy.TestApp//master"]
        )
        self.assertTrue(any(event["event"] == "app-success" for event in self.events(result)))

    def test_missing_signed_remote_is_added_from_canonical_descriptor(self):
        result = self.run_cli(
            "--install", "test-app", "--events", extra_env={"FAKE_REMOTE_PRESENT": "0"}
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        additions = [command for command in self.commands() if command[0] == "remote-add"]
        self.assertEqual(len(additions), 1)
        self.assertEqual(additions[0][-2], "spaced-github")
        self.assertEqual(
            additions[0][-1],
            "https://crhy.github.io/spacedbazaar/spaced-github.flatpakrepo",
        )

    def test_flathub_app_uses_stable_branch(self):
        self._write_catalog(source="flathub")
        payload = json.loads(self.catalog.read_text(encoding="utf-8"))
        payload["apps"][0]["branch"] = "stable"
        self.catalog.write_text(json.dumps(payload), encoding="utf-8")
        result = self.run_cli(
            "--install",
            "test-app",
            "--events",
            extra_env={"FAKE_REMOTE_NAME": "flathub"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        install = [command for command in self.commands() if command[0] == "install"][0]
        self.assertEqual(install[-2:], ["flathub", "io.github.crhy.TestApp//stable"])

    def test_existing_remote_with_unexpected_url_is_rejected(self):
        result = self.run_cli(
            "--install",
            "test-app",
            "--events",
            extra_env={"FAKE_REMOTE_URL": "https://example.invalid/repo/"},
        )
        self.assertEqual(result.returncode, 1)
        failures = [event for event in self.events(result) if event["event"] == "app-failure"]
        self.assertIn("unexpected URL", failures[0]["message"])
        self.assertFalse(any(command[0] == "install" for command in self.commands()))

    def test_install_retries_and_confirms_result(self):
        result = self.run_cli(
            "--install", "test-app", "--events", extra_env={"FAKE_INSTALL_FAILURES": "2"}
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installs = [command for command in self.commands() if command[0] == "install"]
        self.assertEqual(len(installs), 3)

    def test_remote_failure_is_actionable_and_prevents_install(self):
        result = self.run_cli(
            "--install",
            "test-app",
            "--events",
            extra_env={"FAKE_REMOTE_PRESENT": "0", "FAKE_REMOTE_ADD_FAILURE": "1"},
        )
        self.assertEqual(result.returncode, 1)
        failures = [event for event in self.events(result) if event["event"] == "app-failure"]
        self.assertIn("Could not configure spaced-github", failures[0]["message"])
        self.assertFalse(any(command[0] == "install" for command in self.commands()))

    def test_preinstalled_app_is_checked_but_never_installed(self):
        self._write_catalog(preinstalled=True)
        result = self.run_cli(
            "--install", "test-app", "--events", extra_env={"FAKE_PREINSTALLED": "1"}
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([command[0] for command in self.commands()], ["info"])

    def test_already_installed_app_is_skipped(self):
        result = self.run_cli(
            "--install", "test-app", "--events", extra_env={"FAKE_ALREADY_INSTALLED": "1"}
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([command[0] for command in self.commands()], ["info"])


if __name__ == "__main__":
    unittest.main()
