"""Frozen desktop/console entry point and a read-only packaged GUI smoke check."""

import json
import sys
import traceback
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path

from a2router.__main__ import main as cli_main
from a2router.backends import make_backend
from a2router.controller import Controller, config_dir


def smoke_test(report_path, mock=False):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from a2router.ui import MainWindow

    backend = make_backend(mock)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("A2Router")
    window = MainWindow(Controller(backend))  # No saved routes are activated.
    window.show()
    state = {"finished": False, "ok": False}
    timer = QTimer(window)

    def finish():
        if window.busy or state["finished"]:
            return
        state["finished"] = True
        data = {
            "window_title": window.windowTitle(),
            "qt_platform": app.platformName(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "device_rows": window.device_tree.topLevelItemCount(),
            "backend": backend.diagnostics(),
            "simulated": mock,
            "checks": {
                "qt_window_created": True,
                "device_snapshot_populated": len(window.view_devices) == len(backend.list_devices()),
                "no_routes_started": not backend.list_routes(),
            },
            "scope": "Read-only discovery and packaged GUI startup/shutdown; no playback or driver verification",
        }
        state["ok"] = not bool(backend.last_error) and all(data["checks"].values())
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        timer.stop()
        window.exit_application()

    timer.timeout.connect(finish)
    timer.start(100)

    def timeout():
        if not state["finished"]:
            path = Path(report_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"error": "GUI backend smoke check timed out"}), encoding="utf-8")
            state["finished"] = True
            window.exit_application()

    QTimer.singleShot(30000, window, timeout)
    app.exec()
    return 0 if state["ok"] else 1


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    # PyInstaller windowed builds have no stdout/stderr. Keep startup errors
    # inspectable; console builds retain ordinary terminal diagnostics.
    with ExitStack() as stack:
        if sys.stdout is None or sys.stderr is None:
            directory = config_dir() / "logs"
            directory.mkdir(parents=True, exist_ok=True)
            log = stack.enter_context((directory / "desktop.log").open("a", encoding="utf-8"))
            if sys.stdout is None:
                stack.enter_context(redirect_stdout(log))
            if sys.stderr is None:
                stack.enter_context(redirect_stderr(log))
        try:
            if args and args[0] == "--rename-endpoint":
                # Internal elevated operation, not a distributed console program.
                # Never load a profile or install a driver in this child process.
                if len(args) != 3 or sys.platform != "win32":
                    raise ValueError("Invalid endpoint rename request")
                from a2router.backends.windows import WindowsBackend

                backend = WindowsBackend()
                try:
                    if not backend.bridge or not hasattr(backend.bridge, "ar_rename_device"):
                        raise ValueError("Native rename API unavailable")
                    if not backend.bridge.ar_rename_device(args[1], args[2]):
                        raise ValueError(backend._error())
                    return 0
                finally:
                    backend.close()
            if args and args[0] == "--self-test":
                if len(args) not in (2, 3) or (len(args) == 3 and args[2] != "--mock"):
                    raise ValueError("Usage: --self-test REPORT.json [--mock]")
                return smoke_test(args[1], mock=len(args) == 3)
            return cli_main(args or ["gui"])
        except Exception:  # noqa: BLE001 — preserve a windowed startup traceback
            traceback.print_exc()
            return 1
