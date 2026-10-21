import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from a2router.portable import main


def test_packaged_gui_smoke_report(tmp_path):
    app = QApplication.instance() or QApplication([])
    report = tmp_path / "smoke.json"
    assert main(["--self-test", str(report), "--mock"]) == 0
    data = json.loads(report.read_text())
    assert data["simulated"] is True
    assert data["device_rows"] == 4
    assert all(data["checks"].values())
    assert "SIMULATED" in data["backend"]["backend"]
    assert app is QApplication.instance()
