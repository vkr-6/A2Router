import json
import os

import pytest

from a2router.__main__ import main


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))


def test_cli_diagnostics(capsys):
    assert main(["--mock", "diagnostics"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["available"] and "SIMULATED" in data["backend"]


def test_cli_invalid_operation_and_corrupt_state(tmp_path, capsys):
    path = tmp_path / "session.json"
    assert main(["--mock", "--state", str(path), "add-route", "missing", "speakers"]) == 1
    assert "unavailable" in capsys.readouterr().err
    path.write_text("{broken", encoding="utf-8")
    assert main(["--mock", "--state", str(path), "stop"]) == 1
    assert path.read_text() == "{broken"


def test_cli_virtual_profile_and_disabled_routes(tmp_path, capsys):
    path = tmp_path / "session.json"
    assert main(["--mock", "--state", str(path), "create-virtual", "bus"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "bus"
    assert main(["--mock", "--state", str(path), "add-route", "mic", "speakers", "--confirm-monitoring"]) == 0
    route = json.loads(capsys.readouterr().out)
    assert main(["--mock", "--state", str(path), "disable-route", route["id"]]) == 0
    assert json.loads(path.read_text())["routes"][0]["enabled"] is False
    assert main(["--mock", "--state", str(path), "routes"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["status"] == "disabled"


def test_gui_entrypoint_clean_exit(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from a2router import ui

    original = ui.MainWindow

    def make_window(*args, **kwargs):
        window = original(*args, **kwargs)
        QTimer.singleShot(100, window.exit_application)
        return window

    # Keep a Python reference to the QApplication wrapper across app.exec().
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "MainWindow", make_window)
    assert main(["--mock", "--state", str(tmp_path / "session.json"), "gui"]) == 0
    assert app is QApplication.instance()
