"""Private audio-server environment tests; no desktop daemon is touched."""

import tempfile
import unittest
from pathlib import Path

from run_private_pipewire import private_environment


class PrivateEnvironmentTests(unittest.TestCase):
    def test_isolated_socket_layout_and_inherited_environment(self):
        with tempfile.TemporaryDirectory() as runtime:
            inherited = {
                "PATH": "/test/bin",
                "PULSE_RUNTIME_PATH": "/desktop/pulse",
                "PULSE_SERVER": "unix:/desktop/pulse/native",
                "PIPEWIRE_REMOTE": "desktop-server",
            }
            env = private_environment(runtime, inherited)
            self.assertEqual(env["PATH"], "/test/bin")
            self.assertNotIn("PULSE_RUNTIME_PATH", env)
            self.assertEqual(env["XDG_RUNTIME_DIR"], runtime)
            self.assertEqual(env["PIPEWIRE_RUNTIME_DIR"], runtime)
            self.assertEqual(env["PIPEWIRE_REMOTE"], "pipewire-0")
            self.assertEqual(env["PULSE_SERVER"], "unix:" + str(Path(runtime) / "pulse/native"))
            self.assertTrue((Path(runtime) / "pulse").is_dir())
            self.assertEqual(inherited["PULSE_RUNTIME_PATH"], "/desktop/pulse")
            self.assertEqual(private_environment(runtime, env), env)


if __name__ == "__main__":
    unittest.main()
