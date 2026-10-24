"""Workspace tests use explicitly simulated devices; no hardware claims."""

import os
from dataclasses import asdict

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from test_gui import shutdown, wait

from a2router.backends.mock import MockBackend
from a2router.controller import Controller
from a2router.models import BackendError
from a2router.ui import MainWindow


@pytest.fixture
def app(tmp_path):
    app = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    return app


def test_transport_pause_preserves_desired_routes_and_survives_refresh():
    backend = MockBackend()
    controller = Controller(backend)
    active = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    disabled = backend.create_route("mic", "headphones", enabled=False, monitoring_confirmed=True)
    original = controller.snapshot()
    controller.pause_routes()
    controller.refresh()
    assert active.enabled and not disabled.enabled
    assert active.status == "stopped" and not backend.resources
    assert controller.snapshot() == original
    controller.resume_routes()
    assert backend.resources == {active.id}
    assert disabled.status == "disabled"


def test_profile_replace_removes_old_routes_and_parse_failure_is_safe():
    backend = MockBackend()
    controller = Controller(backend)
    old = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    other = MockBackend()
    new = other.create_route("mic", "headphones", monitoring_confirmed=True)
    controller.replace_profile(Controller(other).snapshot())
    assert old.id not in backend.routes and backend.resources == {new.id}
    before = controller.snapshot()
    with pytest.raises(BackendError):
        controller.replace_profile({"version": 99})
    assert controller.snapshot() == before and backend.resources == {new.id}


def test_profile_replace_preserves_stopped_transport():
    backend = MockBackend()
    controller = Controller(backend)
    controller.pause_routes()
    other = MockBackend()
    route = other.create_route("mic", "headphones", monitoring_confirmed=True)
    controller.replace_profile(Controller(other).snapshot())
    controller.refresh()
    assert route.id in backend.routes and backend.routes[route.id].enabled
    assert not backend.transport_running and not backend.resources


def test_workspace_navigation_and_real_transport_actions(app):
    backend = MockBackend()
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        assert [button.text() for button in window.navigation.buttons] == [
            "Audio Routing",
            "Mixer",
            "Devices",
            "Virtual Devices",
            "Calibration",
            "Diagnostics",
            "Settings",
        ]
        assert all(
            button.toolButtonStyle() == Qt.ToolButtonTextUnderIcon for button in window.navigation.buttons
        )
        assert window.navigation.height() <= 58 or not window.isVisible()
        assert window.studio.delay_group.isAncestorOf(window.sync)
        window.studio.actions["stop"].trigger()
        wait(app, window)
        assert route.enabled and route.status == "stopped"
        window.studio.actions["start"].trigger()
        wait(app, window)
        assert route.status == "connected"
        window.studio.actions["emergency"].trigger()
        wait(app, window)
        assert not backend.resources and route.enabled
    finally:
        shutdown(app, window)


def test_model_edits_backend_and_preserves_selection(app):
    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        table = window.studio.output_table
        selected = table.proxy.index(0, 0)
        ident = selected.data(Qt.UserRole)
        table.view.setCurrentIndex(selected)
        row = next(i for i, d in enumerate(table.model.rows) if d["id"] == ident)
        assert not table.model.setData(table.model.index(row, 7), 150)
        assert table.model.setData(table.model.index(row, 7), 42)
        wait(app, window)
        assert backend.devices[ident].properties["controls"]["volume"] == 0.42
        window.refresh()
        wait(app, window)
        assert table.view.currentIndex().data(Qt.UserRole) == ident
        assert table.model.setData(table.model.index(row, 8), "yes")
        wait(app, window)
        assert backend.devices[ident].properties["controls"]["muted"] is True
        assert table.model.data(table.model.index(row, 9)) == "N/A"
    finally:
        shutdown(app, window)


def test_backend_rejection_leaves_observed_volume_unchanged(app, monkeypatch):
    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        table = window.studio.output_table

        def fail(*args):
            raise BackendError("Permission denied")

        monkeypatch.setattr(backend, "set_device_volume", fail)
        row = next(i for i, d in enumerate(table.model.rows) if d["id"] == "speakers")
        table.model.setData(table.model.index(row, 7), 5)
        wait(app, window)
        assert table.model.data(table.model.index(row, 7)) == 75
        assert "Permission denied" in window.error.text()
    finally:
        shutdown(app, window)


def test_profile_open_replaces_and_bad_json_preserves_profile(app, tmp_path):
    from a2router import storage

    backend = MockBackend()
    backend.create_route("mic", "speakers", monitoring_confirmed=True)
    other = MockBackend()
    route = other.create_route("mic", "headphones", monitoring_confirmed=True)
    profile = tmp_path / "profile.json"
    storage.save(profile, Controller(other).snapshot())
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        window.studio.open_path(str(profile))
        wait(app, window)
        assert set(backend.routes) == {route.id}
        assert window.studio.profile_path == profile
        broken = tmp_path / "broken.json"
        broken.write_text("{")
        window.studio.open_path(str(broken))
        wait(app, window)
        assert set(backend.routes) == {route.id}
        assert window.studio.profile_path == profile
        assert "Cannot load" in window.error.text()
    finally:
        shutdown(app, window)


def test_matrix_grid_applies_existing_route_and_restores_rejected_map(app, monkeypatch):
    backend = MockBackend()
    route = backend.create_route("mic", "headphones", monitoring_confirmed=True)
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        window.route_tree.setCurrentItem(window.route_tree.topLevelItem(0))
        matrix = window.studio.matrix
        matrix.load_route()
        matrix.preset.setCurrentText("Stereo swap")
        matrix.load_preset()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
        matrix.apply_route()
        wait(app, window)
        assert route.channel_map == [
            {"source": 0, "destination": 1, "gain": 1.0},
            {"source": 1, "destination": 0, "gain": 1.0},
        ]
        previous = [dict(c) for c in route.channel_map]
        original = backend._connect

        def reject_new(route):
            if route.channel_map != previous:
                raise BackendError("Rejected new DSP path")
            original(route)

        monkeypatch.setattr(backend, "_connect", reject_new)
        matrix.preset.setCurrentText("Identity")
        matrix.load_preset()
        matrix.apply_route()
        wait(app, window)
        assert route.channel_map == previous and route.status == "connected"
        assert "previous mapping restored" in window.error.text()
    finally:
        shutdown(app, window)


def test_telemetry_update_does_not_overwrite_volume_editor_draft(app):
    from PySide6.QtWidgets import QDoubleSpinBox

    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        window.show()
        wait(app, window)
        table = window.studio.output_table
        proxy_row = next(
            r
            for r in range(table.proxy.rowCount())
            if table.proxy.index(r, 0).data(Qt.UserRole) == "speakers"
        )
        index = table.proxy.index(proxy_row, 7)
        table.view.edit(index)
        app.processEvents()
        editor = table.view.findChild(QDoubleSpinBox)
        assert editor is not None
        editor.setValue(33)
        backend.devices["speakers"].properties["controls"].update(peak_available=True, peak=0.1)
        table.model.update_devices([asdict(d) for d in backend.list_devices()])
        app.processEvents()
        assert editor.value() == 33
        assert backend.devices["speakers"].properties["controls"]["volume"] == 0.75
    finally:
        shutdown(app, window)


@pytest.mark.parametrize("theme", ["Light", "Dark", "System"])
def test_compact_workspace_controls_remain_visible_at_target_size(app, theme):
    backend = MockBackend()
    window = MainWindow(Controller(backend))
    try:
        wait(app, window)
        window.studio.theme.setCurrentText(theme)
        window.resize(1366, 768)
        window.show()
        app.processEvents()
        assert window.size().width() == 1366 and window.size().height() == 768
        assert window.navigation.height() <= 58
        assert window.route_tree.isVisible()
        assert window.add_route_button.isVisible()
        assert window.studio.input_table.view.isVisible()
        assert window.studio.output_table.view.isVisible()
        assert window.studio.actions["emergency"].associatedObjects()
        window.studio.open_delay()
        app.processEvents()
        assert window.sync_delay.isVisible()
    finally:
        shutdown(app, window)


def test_profile_unexpected_failure_restores_previous_live_routes(monkeypatch):
    backend = MockBackend()
    controller = Controller(backend)
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    before = controller.snapshot()
    other = MockBackend()
    other.create_route("mic", "headphones", monitoring_confirmed=True)

    def fail(*args, **kwargs):
        raise RuntimeError("Unexpected backend exception")

    monkeypatch.setattr(backend, "create_route", fail)
    with pytest.raises(RuntimeError, match="Unexpected"):
        controller.replace_profile(Controller(other).snapshot())
    assert controller.snapshot() == before
    assert backend.resources == {route.id} and backend.transport_running


def test_emergency_discards_queued_restart_and_stops_after_active_poll(app):
    import threading

    backend = MockBackend()
    route = backend.create_route("mic", "headphones", monitoring_confirmed=True)
    window = MainWindow(Controller(backend))
    release = threading.Event()
    try:
        wait(app, window)
        calls = []
        window.submit(lambda: release.wait(3), persist=False, background=True)
        window.submit(lambda: calls.append("restart should have been discarded"), persist=False)
        window.studio.emergency()
        release.set()
        # Drain both the active observation and the queued emergency stop.
        from time import monotonic, sleep

        deadline = monotonic() + 5
        while (window.busy or window._pending_actions) and monotonic() < deadline:
            app.processEvents()
            sleep(0.005)
        assert not window.busy and not window._pending_actions
        assert calls == [] and not backend.resources and route.enabled
    finally:
        release.set()
        shutdown(app, window)


def test_theme_and_table_layout_survive_window_restart(app):
    first = MainWindow(Controller(MockBackend()))
    wait(app, first)
    first.studio.theme.setCurrentText("Dark")
    first.studio.output_table.view.setColumnWidth(0, 267)
    first.studio.output_table.view.setColumnHidden(2, True)
    shutdown(app, first)
    second = MainWindow(Controller(MockBackend()))
    try:
        wait(app, second)
        assert second.studio.theme.currentText() == "Dark"
        assert second.studio.output_table.view.columnWidth(0) == 267
        assert second.studio.output_table.view.isColumnHidden(2)
    finally:
        shutdown(app, second)
