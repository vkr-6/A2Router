import copy
from dataclasses import asdict
from uuid import uuid4

import pytest

from a2router import storage
from a2router.backends.mock import MockBackend
from a2router.controller import Controller, SessionLock
from a2router.models import LAYOUTS, BackendError, VirtualDevice


@pytest.fixture
def backend():
    return MockBackend()


def test_discovery_stable_classification(backend):
    before = {d.id for d in backend.list_devices()}
    backend.refresh()
    assert before == {d.id for d in backend.list_devices()}
    assert backend.get_device("mic").kind == "input"
    assert backend.get_device("speakers").kind == "output"
    assert "SIMULATED" in backend.diagnostics()["backend"]
    with pytest.raises(BackendError):
        backend.get_device("absent")


def test_empty(backend):
    backend.devices.clear()
    backend.refresh()
    assert backend.list_devices() == []


def test_one_many_and_many_one(backend):
    routes = [
        backend.create_route("mic", dest, monitoring_confirmed=True) for dest in ("speakers", "headphones")
    ]
    routes.append(backend.create_route("speakers.monitor", "headphones"))
    assert len(backend.list_routes()) == len(backend.resources) == 3
    assert all(r.status == "connected" for r in routes)
    with pytest.raises(BackendError, match="Duplicate"):
        backend.create_route("mic", "speakers", monitoring_confirmed=True)
    for route in routes:
        backend.disable_route(route.id)
        backend.disable_route(route.id)
        assert route.status == "disabled"
        backend.enable_route(route.id)
        backend.enable_route(route.id)
        assert route.status == "connected"
        backend.remove_route(route.id)
        backend.remove_route(route.id)
    assert not backend.resources


@pytest.mark.parametrize(
    "source,dest", [("absent", "speakers"), ("mic", "absent"), ("speakers", "headphones")]
)
def test_invalid_devices(backend, source, dest):
    with pytest.raises(BackendError):
        backend.create_route(source, dest)
    assert backend.list_routes() == []


def test_feedback_confirmation_and_layout(backend):
    with pytest.raises(BackendError, match="confirmation"):
        backend.create_route("mic", "speakers")
    with pytest.raises(BackendError, match="Feedback"):
        backend.create_route("speakers.monitor", "speakers")
    backend.devices["headphones"].positions = LAYOUTS["mono"]
    with pytest.raises(BackendError, match="layouts"):
        backend.create_route("speakers.monitor", "headphones")


def test_feedback_cycle(backend):
    a, b = [backend.create_virtual_device(VirtualDevice(name)) for name in ("a", "b")]
    monitor = lambda v: "source:" + v.device_id.removeprefix("sink:") + ".monitor"
    backend.create_route(monitor(a), b.device_id)
    with pytest.raises(BackendError, match="cycle"):
        backend.create_route(monitor(b), a.device_id)


def test_hotplug(backend):
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    device = backend.devices.pop("speakers")
    backend.refresh()
    assert route.status == "pending" and route.enabled
    assert not backend.resources
    backend.devices[device.id] = device
    backend.refresh()
    backend.refresh()
    assert route.status == "connected" and len(backend.resources) == 1


@pytest.mark.parametrize("layout,count", [("mono", 1), ("stereo", 2), ("5.1", 6), ("7.1", 8)])
def test_virtual_layouts(backend, layout, count):
    v = backend.create_virtual_device(VirtualDevice("Music", layout))
    backend.create_virtual_device(v)
    assert backend.devices[v.device_id].channels == count
    assert len(backend.devices[v.device_id].positions) == count
    assert len(backend.virtual_devices) == 1
    backend.remove_virtual_device(v.id)
    backend.remove_virtual_device(v.id)
    assert v.device_id not in backend.devices


def test_invalid_virtual_and_dependency(backend):
    for name, layout in [("x", "9.1"), ("", "stereo"), ("bad\nname", "mono")]:
        with pytest.raises(BackendError):
            backend.create_virtual_device(VirtualDevice(name, layout))
    v = backend.create_virtual_device(VirtualDevice("bus"))
    backend.create_route("source:" + v.device_id.removeprefix("sink:") + ".monitor", "speakers")
    with pytest.raises(BackendError, match="routes"):
        backend.remove_virtual_device(v.id)


def test_roundtrip_restore_missing_and_disabled(backend, tmp_path):
    c = Controller(backend)
    v = backend.create_virtual_device(VirtualDevice("Surround", "5.1"))
    a = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    b = backend.create_route("mic", "headphones", monitoring_confirmed=True)
    backend.disable_route(b.id)
    path = tmp_path / "profile.json"
    c.save(path)
    new = MockBackend()
    speaker = new.devices.pop("speakers")
    restored = Controller(new)
    assert restored.load(path)
    assert new.routes[a.id].status == "pending"
    assert new.routes[b.id].status == "disabled"
    assert v.device_id in new.devices
    new.devices[speaker.id] = speaker
    new.refresh()
    restored.load(path)
    assert len(new.routes) == 2 and len(new.resources) == 1
    assert restored.snapshot() == c.snapshot()


@pytest.mark.parametrize(
    "payload", ["{", "[]", '{"version":999}', '{"version":true,"routes":[],"virtual_devices":[]}']
)
def test_corruption(payload, tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(payload)
    with pytest.raises(BackendError):
        storage.load(path)
    assert path.read_text() == payload


def test_invalid_fields_and_atomic(backend, tmp_path, monkeypatch):
    c = Controller(backend)
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    valid = c.snapshot()
    path = tmp_path / "profile.json"
    storage.save(path, valid)
    before = path.read_bytes()
    for field, value in [("enabled", "false"), ("channel_map", [1]), ("id", "no"), ("source_id", None)]:
        data = copy.deepcopy(valid)
        data["routes"][0][field] = value
        with pytest.raises(BackendError):
            storage.save(path, data)
        assert path.read_bytes() == before
    data = copy.deepcopy(valid)
    data["routes"].append({**data["routes"][0], "id": str(uuid4())})
    with pytest.raises(BackendError, match="Duplicate route"):
        storage.validate(data)

    def fail(*_):
        raise OSError("simulated full disk")

    monkeypatch.setattr(storage.os, "replace", fail)
    backend.disable_route(route.id)
    with pytest.raises(BackendError, match="full disk"):
        storage.save(path, c.snapshot())
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_partial_restore_keeps_desired_virtuals(backend, monkeypatch):
    c = Controller(backend)
    v = VirtualDevice("bus")
    data = {"version": 1, "virtual_devices": [asdict(v)], "routes": []}

    def fail(_):
        raise BackendError("module creation failed")

    monkeypatch.setattr(backend, "_create_virtual", fail)
    assert "module creation failed" in c.restore(data)[0]
    assert c.snapshot()["virtual_devices"] == data["virtual_devices"]


def test_session_lock(tmp_path):
    with SessionLock(tmp_path / "state.lock"), pytest.raises(BackendError, match="Another"):  # noqa: SIM117 — keep lock acquisition inside raises context
        with SessionLock(tmp_path / "state.lock"):
            pass
    with SessionLock(tmp_path / "state.lock"):
        pass


def test_malformed_channel_map(backend):
    from a2router.models import Route

    route = Route("mic", "speakers", channel_map=[[0, 0]])
    with pytest.raises(BackendError, match="Each channel connection"):
        backend._validate_route(route)


def test_inactive_restore_never_starts_audio(backend):
    c = Controller(backend)
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    virtual = backend.create_virtual_device(VirtualDevice("bus"))
    data = c.snapshot()
    other = MockBackend()
    target = Controller(other)
    target.restore(data, activate=False)
    assert other.resources == set()
    assert virtual.device_id not in other.devices
    assert other.routes[route.id].status == "pending"
    target.stop_routes()
    assert not other.routes[route.id].enabled
    assert not other.resources


def test_failed_layout_restore_retains_definition(backend):
    controller = Controller(backend)
    backend.create_route("mic", "speakers", monitoring_confirmed=True)
    data = controller.snapshot()
    other = MockBackend()
    other.devices["speakers"].positions = LAYOUTS["mono"]
    restored = Controller(other)
    assert restored.restore(data)
    assert restored.snapshot()["routes"] == data["routes"]
    assert other.list_routes()[0].status == "error"
    assert not other.resources
    other.devices["speakers"].positions = LAYOUTS["stereo"]
    restored.refresh()
    assert other.list_routes()[0].status == "connected"


def test_pending_virtual_creation_retries(backend, monkeypatch):
    controller = Controller(backend)
    virtual = VirtualDevice("retry")
    original = backend._create_virtual

    def fail(_):
        raise BackendError("temporarily unavailable")

    monkeypatch.setattr(backend, "_create_virtual", fail)
    controller.restore({"version": 1, "virtual_devices": [asdict(virtual)], "routes": []})
    assert virtual.device_id not in backend.devices
    monkeypatch.setattr(backend, "_create_virtual", original)
    controller.refresh()
    assert virtual.device_id in backend.devices


def test_changed_layout_stops_existing_live_connection(backend):
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    backend.devices["speakers"].positions = LAYOUTS["mono"]
    backend.refresh()
    assert route.status == "error"
    assert route.resource_ids == [] and not backend.resources


def test_profile_replaces_confirmation_and_stops_unsafe_monitoring(backend):
    controller = Controller(backend)
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    profile = controller.snapshot()
    profile["routes"][0]["monitoring_confirmed"] = False
    assert controller.restore(profile)
    assert not route.monitoring_confirmed and route.status == "error"
    assert not backend.resources
