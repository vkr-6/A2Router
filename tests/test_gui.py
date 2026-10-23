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


def shutdown(app, window):
    window.exit_application()
    deadline = time.monotonic() + 5
    while not window.executor._shutdown and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def test_refresh_keeps_items_selection_and_status(app):
    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        item = window.device_tree.topLevelItem(1)
        window.device_tree.setCurrentItem(item)
        window.source.setCurrentIndex(window.source.findData("mic"))
        window.error.setText("Previous operation finished")
        window.refresh()
        # Polling does not disable controls or flash an Updating message.
        assert window.add_route_button.isEnabled()
        assert window.error.text() == "Previous operation finished"
        wait(app, window)
        assert window.device_tree.topLevelItem(1) is item
        assert window.device_tree.currentItem() is item
        assert window.source.currentData() == "mic"
        assert window.error.text() == "Previous operation finished"
    finally:
        shutdown(app, window)


class DelayMock(MockBackend):
    def capabilities(self):
        return {**super().capabilities(), "route_delay": True, "live_route_delay": True}

    def set_route_delay(self, route_id, delay, *, allow_restart=False):
        self.routes[route_id].delay_ms = delay


def test_sync_draft_survives_focus_loss_and_poll(app, tmp_path):
    backend = DelayMock()
    route = backend.create_route("mic", "headphones", monitoring_confirmed=True)
    window = MainWindow(Controller(backend), tmp_path / "session.json")
    try:
        wait(app, window)
        window.sync_route.setCurrentIndex(window.sync_route.findData(route.id))
        window.sync_delay.setValue(225)
        window.source.setFocus()
        window.refresh()
        wait(app, window)
        assert window.sync_delay.value() == 225
        assert window.sync_apply.isEnabled()
        window.sync_apply.click()
        wait(app, window)
        assert route.delay_ms == 225 and not window.sync_apply.isEnabled()
        import json

        assert json.loads((tmp_path / "session.json").read_text())["routes"][0]["delay_ms"] == 225
        window.sync_delay.setValue(500)
        window.reset_sync_edit()
        assert window.sync_delay.value() == 225
    finally:
        shutdown(app, window)


def test_action_queued_during_poll_is_not_discarded(app):
    import threading

    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        release = threading.Event()
        calls = []
        window.submit(lambda: release.wait(3), persist=False, background=True)
        window.submit(lambda: calls.append("user action"), persist=False)
        release.set()
        deadline = time.monotonic() + 5
        while (window.busy or window._pending_actions) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert calls == ["user action"]
    finally:
        shutdown(app, window)


def test_sync_metrics_are_native_values_and_update_in_place(app):
    from dataclasses import asdict

    backend = DelayMock()
    route = backend.create_route("mic", "headphones", monitoring_confirmed=True)
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        snapshot = {
            "devices": [asdict(d) for d in backend.list_devices()],
            "routes": [asdict(route)],
            "virtual_devices": [],
            "diagnostics": {
                **backend.diagnostics(),
                "telemetry": {
                    "sessions": [
                        {
                            "source_id": "mic",
                            "sample_rate": 48000,
                            "block_align": 8,
                            "devices": [
                                {
                                    "id": "headphones",
                                    "fill_bytes": 38400,
                                    "target_bytes": 19200,
                                    "sample_rate": 48024,
                                    "underflows": 2,
                                }
                            ],
                        }
                    ]
                },
            },
        }
        window.populate(snapshot)
        item = window.sync.topLevelItem(0)
        assert item.text(3) == "100.0 / 50.0 ms"
        assert item.text(4) == "+500 ppm" and item.text(5) == "2"
        window.populate(snapshot)
        assert window.sync.topLevelItem(0) is item
    finally:
        shutdown(app, window)
