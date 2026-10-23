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


def test_channel_editor_is_optional_and_keeps_edits_through_poll(app):
    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        window.source.setCurrentIndex(window.source.findData("mic"))
        window.destination.setCurrentIndex(window.destination.findData("headphones"))
        assert not window.channel_group.isChecked()
        assert window.channel_table.rowCount() == 2
        window.channel_group.setChecked(True)
        window.channel_table.cellWidget(0, 1).setCurrentIndex(1)
        window.channel_table.cellWidget(1, 1).setCurrentIndex(0)
        window.channel_table.cellWidget(1, 2).setValue(-6)
        window.refresh()
        wait(app, window)
        assert window.channel_table.cellWidget(0, 1).currentData() == 1
        assert window.channel_table.cellWidget(1, 2).value() == -6
        window.monitor_confirm.setChecked(True)
        window.add_route_button.click()
        wait(app, window)
        route = backend.list_routes()[0]
        assert route.channel_map[0] == {"source": 0, "destination": 1, "gain": 1.0}
        assert route.channel_map[1]["gain"] == pytest.approx(0.501187, abs=1e-6)
        assert "Custom" in window.route_tree.topLevelItem(0).text(4)
        assert not window.windowIcon().isNull()
    finally:
        shutdown(app, window)


def test_cable_tab_never_installs_on_start_or_refresh(app, monkeypatch):
    from test_windows import CableBridge

    from a2router.backends.windows import WindowsBackend

    backend = WindowsBackend(CableBridge())
    calls = []
    monkeypatch.setattr(backend, "configure_cable", lambda name: calls.append(name))
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        window.refresh()
        wait(app, window)
        assert calls == []
        window.virtual_name.setText("Applications")
        # Source checkout has no extracted payload. Enable the control only for
        # this simulated action; no installer exists in this test.
        window.install_cable_button.setProperty("capable", True)
        window.install_cable_button.setEnabled(True)
        window.install_cable_button.click()
        wait(app, window)
        assert calls == ["Applications"]
        assert not backend.virtual_devices
    finally:
        shutdown(app, window)


def test_omitting_source_channels_requires_confirmation(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        window.source.setCurrentIndex(window.source.findData("mic"))
        window.destination.setCurrentIndex(window.destination.findData("headphones"))
        window.channel_group.setChecked(True)
        window.channel_table.setRowCount(1)
        window.monitor_confirm.setChecked(True)
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
        window.add_route()
        assert backend.list_routes() == []
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
        window.add_route()
        wait(app, window)
        assert len(backend.list_routes()[0].channel_map) == 1
    finally:
        shutdown(app, window)


def test_dashboard_master_controls_and_missing_peak_are_honest(app):
    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        assert window.navigation.item(0).text() == "Audio"
        assert window.header_title.text() == "Audio"
        assert not window.menuBar().actions()
        card = window.dashboard.cards["speakers"]
        assert len(window.dashboard.cards) == 3
        assert not card.graph.samples
        card.volume.setValue(35)
        deadline = time.monotonic() + 2
        while (
            time.monotonic() < deadline
            and backend.devices["speakers"].properties["controls"]["volume"] != 0.35
        ):
            app.processEvents()
            time.sleep(0.01)
        wait(app, window)
        assert backend.devices["speakers"].properties["controls"]["volume"] == 0.35
        card.mute.click()
        wait(app, window)
        assert backend.devices["speakers"].properties["controls"]["muted"]
    finally:
        shutdown(app, window)


def test_virtual_tab_shows_existing_cable_and_configures_capture_16_channels(app):
    from test_device_controls import ConfigurationBridge

    from a2router.backends.windows import WindowsBackend

    backend = WindowsBackend(ConfigurationBridge())
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        assert window.virtual_tree.topLevelItemCount() == 3
        assert window.cable_endpoint.count() == 3
        window.cable_endpoint.setCurrentIndex(window.cable_endpoint.findData("cable-out"))
        window.scan_formats_button.click()
        wait(app, window)
        assert window.channel_choice.findData(16) >= 0
        window.channel_choice.setCurrentIndex(window.channel_choice.findData(16))
        assert "24.576" in window.format_data_rate.text()
        window.apply_format_button.click()
        wait(app, window)
        assert backend.get_device("cable-out").channels == 16
        window.source.setCurrentIndex(window.source.findData("cable-out"))
        window.destination.setCurrentIndex(window.destination.findData("cable-16"))
        window.channel_group.setChecked(True)
        assert window.channel_table.cellWidget(0, 0).count() == 16
        window.endpoint_name.setText("Applications")
        window.rename_button.click()
        wait(app, window)
        assert backend.get_device("cable-out").name == "Applications"
    finally:
        shutdown(app, window)


def test_main_audio_filter_preserves_cards_and_peak_history(app):
    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        card = window.dashboard.cards["speakers"]
        card.graph.observe(1.0, 0.25)
        card.graph.observe(1.0, 0.25)
        card.graph.observe(1.25, 0.5)
        assert len(card.graph.samples) == 2
        assert card.graph.available
        card.graph.observe(1.5, None)
        assert not card.graph.available
        window.dashboard.filter_kind.setCurrentText("Inputs")
        assert window.dashboard.card_order == ["mic"]
        window.dashboard.filter_kind.setCurrentText("All devices")
        window.dashboard.search.setText("speakers")
        assert window.dashboard.card_order == ["speakers"]
        assert window.dashboard.cards["speakers"] is card
        assert window.dashboard.counters["outputs"].text() == "2"
    finally:
        shutdown(app, window)
