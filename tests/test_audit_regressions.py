"""Failure-path regressions use simulated backends, never hardware or installers."""

import pytest
from test_calibration import CaptureBackend

from a2router import storage
from a2router.backends.mock import MockBackend
from a2router.controller import Controller
from a2router.models import BackendError


def test_disabled_reconciliation_releases_live_resource():
    backend = MockBackend()
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    route.enabled = False
    backend.refresh()
    assert route.status == "disabled" and not route.resource_ids and not backend.resources


def test_profile_rollback_stops_resources_created_before_exception(monkeypatch):
    backend = MockBackend()
    original = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    controller = Controller(backend)
    other = MockBackend()
    other.create_route("mic", "headphones", monitoring_confirmed=True)
    replacement = Controller(other).snapshot()
    real = controller.restore
    first = True

    def restore(data, activate=True):
        nonlocal first
        result = real(data, activate=activate)
        if first:
            first = False
            backend.transport_running = True
            backend.refresh()
            raise RuntimeError("Failure after resources were started")
        return result

    monkeypatch.setattr(controller, "restore", restore)
    with pytest.raises(RuntimeError, match="resources were started"):
        controller.replace_profile(replacement)
    assert backend.resources == {original.id}
    assert set(backend.routes) == {original.id}
    assert backend.transport_running


def test_emergency_latch_blocks_queued_calibration():
    backend = CaptureBackend()
    controller = Controller(backend)
    controller.request_emergency_stop()
    with pytest.raises(BackendError, match="Emergency stop"):
        controller.measure_calibration(
            "mic", ["speakers", "headphones"], "speakers", 3, -36, 0, lambda *_: None
        )
    assert not backend.capture_calls
    assert controller._emergency.is_set()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_invalid_json_export_preserves_existing_file(tmp_path, value):
    path = tmp_path / "export.json"
    path.write_text('{"valid": true}')
    with pytest.raises(BackendError, match="Cannot save"):
        storage.atomic_json(path, {"value": value})
    assert path.read_text() == '{"valid": true}'
    assert list(tmp_path.iterdir()) == [path]


def test_uncreatable_config_parent_has_structured_error(tmp_path):
    parent = tmp_path / "existing-file"
    parent.write_text("keep")
    with pytest.raises(BackendError, match="Cannot save"):
        storage.atomic_json(parent / "config.json", {})
    assert parent.read_text() == "keep"


@pytest.mark.parametrize("field", ["enabled", "monitoring_confirmed"])
def test_string_booleans_do_not_start_routes(field):
    backend = MockBackend()
    kwargs = {"monitoring_confirmed": True, field: "false"}
    with pytest.raises(BackendError, match="booleans"):
        backend.create_route("mic", "speakers", **kwargs)
    assert not backend.routes and not backend.resources


@pytest.mark.parametrize("config", [{"name": None}, {"name": "bus", "id": "invalid"}, {"unknown": 1}])
def test_invalid_virtual_definitions_are_structured_and_allocate_nothing(config):
    backend = MockBackend()
    initial = set(backend.devices)
    with pytest.raises(BackendError):
        backend.create_virtual_device(config)
    assert set(backend.devices) == initial and not backend.virtual_devices


def test_failed_replacement_cleanup_retains_resource_identity(monkeypatch):
    backend = MockBackend()
    controller = Controller(backend)
    other = MockBackend()
    replacement_route = other.create_route("mic", "headphones", monitoring_confirmed=True)
    real_restore = controller.restore

    def restore(data, activate=True):
        real_restore(data, activate=activate)
        backend.transport_running = True
        backend.refresh()
        raise RuntimeError("Replacement failed after start")

    real_disconnect = backend._disconnect

    def cannot_disconnect(route):
        if route.resource_ids:
            raise BackendError("Audio server refused cleanup")
        real_disconnect(route)

    monkeypatch.setattr(controller, "restore", restore)
    monkeypatch.setattr(backend, "_disconnect", cannot_disconnect)
    with pytest.raises(BackendError, match="retained for cleanup"):
        controller.replace_profile(Controller(other).snapshot())
    assert not backend.transport_running
    assert backend.routes[replacement_route.id].resource_ids == [replacement_route.id]
    assert backend.resources == {replacement_route.id}
