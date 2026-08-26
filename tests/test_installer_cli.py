# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
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
        self.bundle = self.work / "fixture.flatpak"
        self.bundle.write_bytes(b"valid-flatpak-fixture\n")
        self.log = self.work / "commands.jsonl"
        self.counter = self.work / "install-count"
        self.marker = self.work / "installed"
        self.catalog = self.work / "catalog.json"
        self.release = self.work / "release.json"
        self._write_catalog()
        self._write_release()
        self._write_fake_commands()

        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PYTHONPATH": str(ROOT / "src"),
                "PATH": str(self.fake_bin),
                "SPACED_WELCOME_CATALOG": str(self.catalog),
                "SPACED_WELCOME_ARCH": "x86_64",
                "SPACED_WELCOME_CACHE_DIR": str(self.work / "cache"),
                "SPACED_WELCOME_CURL": str(self.fake_bin / "curl"),
                "SPACED_WELCOME_FLATPAK": str(self.fake_bin / "flatpak"),
                "SPACED_WELCOME_OSTREE": str(self.fake_bin / "ostree"),
                "SPACED_WELCOME_RETRY_DELAY": "0",
                "SPACED_WELCOME_ATTEMPTS": "3",
                "FAKE_RELEASE": str(self.release),
                "FAKE_BUNDLE": str(self.bundle),
                "FAKE_LOG": str(self.log),
                "FAKE_OSTREE_INIT_LOG": str(self.work / "ostree-init.jsonl"),
                "FAKE_COUNTER": str(self.counter),
                "FAKE_MARKER": str(self.marker),
                "FAKE_REF": "app/io.github.crhy.TestApp/x86_64/master",
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def _write_catalog(self, *, preinstalled: bool = False):
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
                    "source": {
                        "type": "github-release",
                        "repository": "crhy/TestApp",
                        "assets": {"x86_64": {"name": "TestApp.flatpak"}},
                    },
                }
            ],
        }
        self.catalog.write_text(json.dumps(payload), encoding="utf-8")

    def _write_release(self, *, digest: str | None = None, url: str | None = None):
        if digest is None:
            digest = f"sha256:{hashlib.sha256(self.bundle.read_bytes()).hexdigest()}"
        if url is None:
            url = "https://github.com/crhy/TestApp/releases/download/v1.0.0/TestApp.flatpak"
        payload = {
            "tag_name": "v1.0.0",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "id": 123,
                    "name": "TestApp.flatpak",
                    "state": "uploaded",
                    "size": self.bundle.stat().st_size,
                    "digest": digest,
                    "browser_download_url": url,
                }
            ],
        }
        self.release.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _executable(path: Path, source: str):
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        path.chmod(0o755)

    def _write_fake_commands(self):
        self._executable(
            self.fake_bin / "curl",
            r"""
            #!/usr/bin/python3
            import os, pathlib, shutil, sys
            args = sys.argv[1:]
            output = pathlib.Path(args[args.index('--output') + 1])
            url = args[-1]
            output.parent.mkdir(parents=True, exist_ok=True)
            if '/api.github.com/repos/' in url:
                shutil.copyfile(os.environ['FAKE_RELEASE'], output)
            else:
                shutil.copyfile(os.environ['FAKE_BUNDLE'], output)
                print('Download 100% complete', file=sys.stderr)
            """,
        )
        self._executable(
            self.fake_bin / "ostree",
            r"""
            #!/usr/bin/python3
            import os, pathlib, sys
            args = sys.argv[1:]
            if len(args) >= 2 and args[0].startswith('--repo=') and args[1] == 'init':
                repository = pathlib.Path(args[0].split('=', 1)[1])
                log = os.environ['FAKE_OSTREE_INIT_LOG']
                with pathlib.Path(log).open('a', encoding='utf-8') as target:
                    target.write(repository.as_posix() + '\n')
                repository.mkdir(parents=True, exist_ok=True)
                (repository / 'objects').mkdir(exist_ok=True)
                (repository / 'staged').mkdir(exist_ok=True)
                (repository / 'staged' / 'import').mkdir(exist_ok=True)
                (repository / 'tmp').mkdir(exist_ok=True)
            raise SystemExit(0)
            """,
        )
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
                print('flathub')
                raise SystemExit(0)
            if command == 'remote-add':
                raise SystemExit(0)
            if command == 'build-import-bundle':
                print('Importing ' + os.environ['FAKE_REF'] + ' (0123456789abcdef)')
                raise SystemExit(0)
            if command == 'install':
                target = args[-1]
                if target.startswith('/') and not target.endswith('.flatpak'):
                    print('bundle filename lost .flatpak suffix', file=sys.stderr)
                    raise SystemExit(90)
                counter = pathlib.Path(os.environ['FAKE_COUNTER'])
                count = int(counter.read_text() if counter.exists() else '0') + 1
                counter.write_text(str(count))
                failures = int(os.environ.get('FAKE_INSTALL_FAILURES', '0'))
                print(f'Flatpak install attempt {count}')
                if count <= failures:
                    raise SystemExit(1)
                pathlib.Path(os.environ['FAKE_MARKER']).touch()
                raise SystemExit(0)
            if command == 'info':
                if os.environ.get('FAKE_PREINSTALLED') == '1' or pathlib.Path(os.environ['FAKE_MARKER']).exists():
                    raise SystemExit(0)
                raise SystemExit(1)
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

    def test_resolve_returns_exact_verified_asset_metadata(self):
        result = self.run_cli("--resolve", "test-app")
        self.assertEqual(result.returncode, 0, result.stderr)
        resolved = json.loads(result.stdout)
        self.assertEqual(resolved["name"], "TestApp.flatpak")
        self.assertEqual(resolved["arch"], "x86_64")
        self.assertEqual(resolved["app_id"], "io.github.crhy.TestApp")
        self.assertTrue(resolved["digest"].startswith("sha256:"))

    def test_install_preserves_flatpak_suffix_and_streams_progress(self):
        result = self.run_cli("--install", "test-app", "--events")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.events(result)
        self.assertTrue(any(event["event"] == "app-start" for event in events))
        self.assertTrue(any(event["event"] == "app-success" for event in events))
        self.assertTrue(any("Download 100%" in event.get("message", "") for event in events))
        installs = [command for command in self.commands() if command[0] == "install"]
        self.assertEqual(len(installs), 1)
        self.assertTrue(installs[0][-1].endswith(".flatpak"), installs[0][-1])
        self.assertNotRegex(Path(installs[0][-1]).name, r"\.flatpak\.[A-Za-z0-9]+$")

    def test_digest_mismatch_is_rejected_before_flatpak_install(self):
        self._write_release(digest="sha256:" + "0" * 64)
        result = self.run_cli("--install", "test-app", "--events")
        self.assertEqual(result.returncode, 1)
        events = self.events(result)
        failures = [event for event in events if event["event"] == "app-failure"]
        self.assertEqual(len(failures), 1)
        self.assertIn("SHA-256 verification failed", failures[0]["message"])
        self.assertFalse(any(command[0] == "install" for command in self.commands()))

    def test_inspection_repository_lives_in_host_visible_cache(self):
        result = self.run_cli("--install", "test-app", "--events")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        init_log = self.work / "ostree-init.jsonl"
        lines = [line for line in init_log.read_text().splitlines() if line]
        self.assertEqual(len(lines), 1)
        repository = Path(lines[0])
        # Inside the Spaced Welcome Flatpak, ostree and flatpak run on the
        # host, so the import repo must live under the shared xdg-cache
        # directory, not the sandbox-private temp dir.
        cache = Path(self.environment["SPACED_WELCOME_CACHE_DIR"])
        self.assertTrue(repository.is_relative_to(cache), repository)

    def test_flatpak_ref_mismatch_is_rejected_before_install(self):
        result = self.run_cli(
            "--install",
            "test-app",
            "--events",
            extra_env={"FAKE_REF": "app/io.github.crhy.Wrong/x86_64/master"},
        )
        self.assertEqual(result.returncode, 1)
        failures = [event for event in self.events(result) if event["event"] == "app-failure"]
        self.assertIn("Flatpak ref mismatch", failures[0]["message"])
        self.assertFalse(any(command[0] == "install" for command in self.commands()))

    def test_install_retries_independently_and_confirms_result(self):
        result = self.run_cli(
            "--install",
            "test-app",
            "--events",
            extra_env={"FAKE_INSTALL_FAILURES": "2"},
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        installs = [command for command in self.commands() if command[0] == "install"]
        self.assertEqual(len(installs), 3)
        self.assertTrue(any(event["event"] == "app-success" for event in self.events(result)))

    def test_unexpected_download_host_is_rejected(self):
        self._write_release(url="https://example.com/crhy/TestApp/releases/download/v1.0.0/TestApp.flatpak")
        result = self.run_cli("--install", "test-app", "--events")
        self.assertEqual(result.returncode, 1)
        failure = [event for event in self.events(result) if event["event"] == "app-failure"][0]
        self.assertIn("unexpected download URL", failure["message"])

    def test_preinstalled_app_is_checked_but_never_downloaded(self):
        self._write_catalog(preinstalled=True)
        result = self.run_cli(
            "--install",
            "test-app",
            "--events",
            extra_env={"FAKE_PREINSTALLED": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        events = self.events(result)
        self.assertTrue(any(event["event"] == "app-skipped" for event in events))
        commands = self.commands()
        self.assertEqual([command[0] for command in commands], ["info"])


if __name__ == "__main__":
    unittest.main()
