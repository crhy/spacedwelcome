import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_debian_package_is_reproducible(self):
        environment = os.environ.copy()
        environment["SOURCE_DATE_EPOCH"] = "1700000000"

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            environment["SPACED_WELCOME_OUTPUT_DIR"] = first
            subprocess.run(
                ["bash", ROOT / "packaging/build-deb.sh"],
                check=True,
                env=environment,
                stdout=subprocess.DEVNULL,
            )
            time.sleep(1)
            environment["SPACED_WELCOME_OUTPUT_DIR"] = second
            subprocess.run(
                ["bash", ROOT / "packaging/build-deb.sh"],
                check=True,
                env=environment,
                stdout=subprocess.DEVNULL,
            )

            name = f"spaced-welcome_{(ROOT / 'VERSION').read_text().strip()}_all.deb"
            self.assertEqual((Path(first) / name).read_bytes(), (Path(second) / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
