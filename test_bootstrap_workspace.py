import subprocess
import unittest
from unittest import mock

from scripts import bootstrap_workspace


class BootstrapWorkspaceTests(unittest.TestCase):
    def test_install_is_verified_in_fresh_interpreter(self):
        # The current process can keep a stale import path after pip creates
        # the user site directory; the fresh process is what later tests use.
        installed = subprocess.CompletedProcess(args=[], returncode=0)
        verified = subprocess.CompletedProcess(args=[], returncode=0, stdout="\n")
        with mock.patch.object(bootstrap_workspace, "missing_imports", return_value=["flask"]), mock.patch.object(
            bootstrap_workspace.subprocess, "run", side_effect=[installed, verified]
        ) as run:
            self.assertEqual(bootstrap_workspace.main(), 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn("-c", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
