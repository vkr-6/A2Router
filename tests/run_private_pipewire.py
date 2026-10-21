"""Run integration tests on a private PipeWire server, leaving desktop audio alone.

Use: dbus-run-session -- .venv/bin/python tests/run_private_pipewire.py
Optional extracted Ubuntu test packages: build/pipewire-root/{usr/bin,usr/share,...}.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    repo = Path(__file__).resolve().parents[1]
    root = repo / "build" / "pipewire-root" / "usr"
    env = os.environ.copy()
    if root.exists():
        env.update(
            {
                "PATH": f"{root / 'bin'}:{env.get('PATH', '')}",
                "LD_LIBRARY_PATH": str(root / "lib/x86_64-linux-gnu"),
                "PIPEWIRE_MODULE_DIR": str(root / "lib/x86_64-linux-gnu/pipewire-0.3"),
                "PIPEWIRE_CONFIG_DIR": str(root / "share/pipewire"),
                "WIREPLUMBER_CONFIG_DIR": str(root / "share/wireplumber"),
                "WIREPLUMBER_DATA_DIR": str(root / "share/wireplumber"),
                "WIREPLUMBER_MODULE_DIR": str(root / "lib/x86_64-linux-gnu/wireplumber-0.4"),
            }
        )
    for binary in ("pipewire", "pipewire-pulse", "wireplumber", "pactl", "pacat", "parec"):
        if not shutil.which(binary, path=env["PATH"]):
            raise SystemExit(f"Missing test dependency: {binary}")
    with tempfile.TemporaryDirectory(prefix="a2router-pw-") as runtime:
        env.update(
            {
                "XDG_RUNTIME_DIR": runtime,
                "PIPEWIRE_RUNTIME_DIR": runtime,
                "PULSE_RUNTIME_PATH": runtime + "/pulse",
                "PULSE_SERVER": "unix:" + runtime + "/pulse/native",
                "A2ROUTER_INTEGRATION": "1",
                "A2ROUTER_PCM_TEST": "1",
            }
        )
        processes, logs = [], []
        try:
            for binary in ("pipewire", "pipewire-pulse", "wireplumber"):
                log = tempfile.TemporaryFile()  # noqa: SIM115 — all logs closed together in finally
                logs.append((binary, log))
                processes.append(subprocess.Popen([binary], env=env, stdout=log, stderr=log))
                time.sleep(0.3)
            for _ in range(40):
                check = subprocess.run(
                    ["pactl", "info"], env=env, capture_output=True, timeout=3, check=False
                )
                if check.returncode == 0:
                    break
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("Private audio daemon exited")
                time.sleep(0.1)
            else:
                raise RuntimeError("Private audio server did not become available")
            env["A2ROUTER_PRIVATE_PULSE_PID"] = str(processes[1].pid)
            env["A2ROUTER_PRIVATE_SERVER"] = "1"
            print(check.stdout.decode(), flush=True)
            time.sleep(1)
            return subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "tests/test_integration.py"],
                cwd=repo,
                env=env,
                check=False,
            ).returncode
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            for name, log in logs:
                log.seek(0)
                contents = log.read().decode(errors="replace")
                if contents:
                    print(f"{name} diagnostics:\n{contents[-5000:]}", file=sys.stderr)
                log.close()


if __name__ == "__main__":
    raise SystemExit(main())
