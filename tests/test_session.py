import unittest
from unittest.mock import patch

from spaced_welcome import session
from spaced_welcome.catalog import SOURCE_ROOT_CATALOG, load_catalog
from spaced_welcome.installer import InstallError, Installer
from spaced_welcome.cli import main


class SessionTests(unittest.TestCase):
    def test_live_kernel_flag_survives_medium_unmount(self):
        with patch.object(session.Path, "exists", return_value=False), patch.object(
            session.Path, "read_text", return_value="quiet boot=live components"
        ):
            self.assertTrue(session.is_live_session())

    def test_installed_boot_and_similar_tokens_are_not_live(self):
        for cmdline in ("root=UUID=123 ro quiet", "notboot=live boot=live-other"):
            with self.subTest(cmdline=cmdline), patch.object(
                session.Path, "exists", return_value=False
            ), patch.object(session.Path, "read_text", return_value=cmdline):
                self.assertFalse(session.is_live_session())

    def test_both_live_mount_locations(self):
        for present in ([True], [False, True]):
            with patch.object(session.Path, "exists", side_effect=present):
                self.assertTrue(session.is_live_session())

    def test_unreadable_boot_context_blocks_installation(self):
        with patch.object(session.Path, "exists", return_value=False), patch.object(
            session.Path, "read_text", side_effect=PermissionError
        ):
            self.assertTrue(session.is_live_session())

    def test_backend_blocks_before_any_commands(self):
        installer = Installer(load_catalog(SOURCE_ROOT_CATALOG))
        app = installer.catalog.apps[0]
        with patch("spaced_welcome.installer.is_live_session", return_value=True), patch(
            "spaced_welcome.installer.subprocess.run"
        ) as run, patch("spaced_welcome.installer.subprocess.Popen") as popen:
            with self.assertRaisesRegex(InstallError, "restart"):
                installer.install([app])
            self.assertFalse(installer.install_app(app))
            run.assert_not_called()
            popen.assert_not_called()

    def test_cli_reports_reboot_requirement(self):
        with patch("spaced_welcome.installer.is_live_session", return_value=True), patch(
            "builtins.print"
        ) as output:
            self.assertEqual(main(["--install", "suggested", "--events"]), 2)
            self.assertIn("restart", output.call_args.args[0])
