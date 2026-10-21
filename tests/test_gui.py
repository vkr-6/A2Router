import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time

import pytest
from PySide6.QtWidgets import QApplication

from a2router.backends.mock import MockBackend
from a2router.controller import Controller
from a2router.ui import MainWindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def wait(app, window):
    deadline = time.monotonic() + 10
    while window.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not window.busy


def test_gui_controls_and_shutdown(app, tmp_path):
    backend = MockBackend()
    window = MainWindow(Controller(backend), tmp_path / "session.json")
    try:
        window.show()
        wait(app, window)
        assert window.windowTitle().startswith("A2Router")
        assert window.device_tree.topLevelItemCount() == 4
        window.source.setCurrentIndex(window.source.findData("mic"))
        window.destination.setCurrentIndex(window.destination.findData("speakers"))
        window.add_route_button.click()
        wait(app, window)
        assert "confirmation" in window.error.text()
        window.monitor_confirm.setChecked(True)
        window.add_route_button.click()
        wait(app, window)
        assert window.route_tree.topLevelItemCount() == 1
        window.route_tree.topLevelItem(0).setSelected(True)
        window.route_action("disable_route")
        wait(app, window)
        assert backend.list_routes()[0].status == "disabled"
        window.virtual_name.setText("Applications")
        window.create_virtual_button.click()
        wait(app, window)
        assert window.virtual_tree.topLevelItemCount() == 1
        window.virtual_tree.topLevelItem(0).setSelected(True)
        window.remove_virtual()
        wait(app, window)
        assert not backend.virtual_devices
        assert (tmp_path / "session.json").exists()
        window.close()
        assert not window.exiting  # Close does not stop transport.
    finally:
        window.exit_application()
        deadline = time.monotonic() + 5
        while not window.executor._shutdown and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
    assert window.executor._shutdown
