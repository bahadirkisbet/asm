"""Example failure output must stay safe and owned temporary files must be removed."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ExampleTests(unittest.TestCase):
    def test_failed_mcp_start_hides_raw_output_and_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory(prefix="asm-example-failure-") as temporary:
            directory = Path(temporary)
            fake = directory / "failing-asm"
            sentinel = "SYNTHETIC-example-upstream-output"
            fake.write_text("#!/bin/sh\nprintf '" + sentinel + "\\n'\nprintf '" + sentinel + "\\n' >&2\nexit 1\n")
            fake.chmod(0o700)
            result = subprocess.run([sys.executable, str(ROOT / "examples/run.py"), "file", "--binary", str(fake)], env=dict(os.environ, TMPDIR=temporary), capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr.strip(), '{"error":"example_failed"}')
            self.assertNotIn(sentinel, result.stdout + result.stderr)
            self.assertEqual(list(directory.glob("asm-example-*")), [])


if __name__ == "__main__":
    unittest.main()
