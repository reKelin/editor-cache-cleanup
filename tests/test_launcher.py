import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows launcher")
class LauncherTests(unittest.TestCase):
    def test_system_python_without_project_venv(self):
        with tempfile.TemporaryDirectory(prefix="cleanup launcher ") as directory:
            root = Path(directory)
            shutil.copyfile(Path(__file__).resolve().parents[1] / "cleanup.cmd", root / "cleanup.cmd")
            script = root / "editor_cleanup.py"
            env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["SystemRoot"])
            for exit_code in (0, 7):
                script.write_text("import sys; print('started'); sys.exit({})".format(exit_code))
                result = subprocess.run([os.environ["COMSPEC"], "/d", "/c", "cleanup.cmd", "--version"],
                                        cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, exit_code, result.stderr)
                self.assertEqual(result.stdout.strip(), "started")
