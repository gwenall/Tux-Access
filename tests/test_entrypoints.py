"""Check package startup without relying on the checkout's working directory."""
from importlib.resources import files
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tux_access
from tux_access.installation.install import _prepare_native


class EntrypointTests(unittest.TestCase):
    def test_absolute_entrypoint_runs_with_isolated_imports_from_another_directory(self):
        entrypoint = Path(tux_access.__file__).with_name('__main__.py')
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-I', str(entrypoint), '--help'],
                                    cwd=directory, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Tux Access', result.stdout)
        self.assertIn('--oauth-callback', result.stdout)

    def test_native_preparation_uses_the_bundled_helper(self):
        original_is_file = Path.is_file
        with tempfile.TemporaryDirectory() as directory:
            with patch('tux_access.installation.install.Path.home', return_value=Path(directory)), \
                 patch.object(Path, 'is_file', lambda path: path == Path('/etc/arch-release') or original_is_file(path)), \
                 patch('shutil.which', return_value='/fixture/tool'), \
                 patch('tux_access.installation.install.subprocess.Popen') as spawn:
                spawn.return_value.poll.return_value = 0
                spawn.return_value.returncode = 0
                _prepare_native(lambda *args: None, None)
            command = spawn.call_args.args[0]
            self.assertEqual(command[0], '/bin/bash')
            self.assertEqual(command[2:], ['--managed'])
            self.assertEqual(Path(command[1]), files('tux_access.resources') / 'prepare_arch_compat.sh')
            self.assertIn('set -eu', Path(command[1]).read_text())


if __name__ == '__main__':
    unittest.main()
