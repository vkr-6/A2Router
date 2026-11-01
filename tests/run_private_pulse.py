"""Test real PulseAudio channel maps on an isolated, unprivileged server."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix="a2router-pulse-") as directory:
        runtime = Path(directory)
        config = runtime / "test.pa"
        config.write_text("load-module module-native-protocol-unix socket=" + str(runtime / "native") + "\n")
        env = {
            **os.environ,
            "PULSE_SERVER": "unix:" + str(runtime / "native"),
            "PULSE_RUNTIME_PATH": directory,
        }
        env.update(XDG_CONFIG_HOME=str(runtime / "config"), XDG_CACHE_HOME=str(runtime / "cache"))
        args = [
            env.get("A2ROUTER_PULSE_BINARY", "pulseaudio"),
            "-nF",
            str(config),
            "--daemonize=no",
            "--exit-idle-time=-1",
            "--use-pid-file=no",
        ]
        if module_path := env.get("A2ROUTER_PULSE_MODULE_PATH"):
            args += ["--dl-search-path=" + module_path]
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(args, env=env, stdout=log, stderr=log)
            try:
                for _ in range(50):
                    if process.poll() is not None:
                        raise RuntimeError("Private PulseAudio server exited")
                    if (
                        subprocess.run(
                            ["pactl", "info"], env=env, capture_output=True, check=False
                        ).returncode
                        == 0
                    ):
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Private PulseAudio server unavailable")
                env["A2ROUTER_PULSE_MATRIX_TEST"] = "1"
                return subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "tests/test_pulse_matrix.py"],
                    env=env,
                    cwd=Path(__file__).resolve().parents[1],
                    check=False,
                ).returncode
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                log.seek(0)
                print(log.read().decode(errors="replace")[-5000:], file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
