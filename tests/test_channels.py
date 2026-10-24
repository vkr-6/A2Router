"""Matrix control tests are simulated; native sample tests run through CTest."""

from copy import deepcopy

import pytest
from test_windows import CableBridge, DelayBridge

from a2router import storage
from a2router.backends.mock import MockBackend
from a2router.backends.windows import WindowsBackend
from a2router.channels import validate_channel_map
from a2router.controller import Controller
from a2router.models import BackendError

MAP = [
    {"source": 0, "destination": 1, "gain": 0.5},
    {"source": 0, "destination": 0, "gain": 1.0},
    {"source": 1, "destination": 0, "gain": 0.5},
]


class MatrixBridge(DelayBridge):
    def __init__(self):
        super().__init__()
        self.matrices = []

    def ar_source_start_matrix(self, source, input, ids, delays, matrices):
        self.matrices.append((source, input, ids, delays, matrices))
        return self.ar_source_start(source, input, ids)


def test_matrix_native_call_persistence_and_poll_does_not_restart(tmp_path):
    bridge = MatrixBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    controller = Controller(backend)
    route = backend.create_route("wasapi-loopback:default", "headphones", channel_map=MAP)
    assert route.status == "connected"
    assert bridge.matrices[-1] == ("default", 0, "headphones", "0", "3 0 1 0.5 0 0 1.0 1 0 0.5")
    before = len(bridge.starts)
    backend.refresh()
    assert len(bridge.starts) == before
    backend.set_route_delay(route.id, 20, allow_restart=False)
    backend.refresh()
    assert len(bridge.starts) == before
    backend.disable_route(route.id)
    assert not bridge.sessions
    backend.enable_route(route.id)
    assert len(bridge.matrices) == 2
    controller.save(tmp_path / "profile.json")
    restored = WindowsBackend(MatrixBridge())
    assert Controller(restored).restore(storage.load(tmp_path / "profile.json")) == []
    assert restored.list_routes()[0].channel_map == MAP
    backend.close()
    restored.close()


def test_matrix_mixed_with_automatic_fanout():
    bridge = MatrixBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    backend.create_route("wasapi-loopback:default", "headphones")
    backend.create_route("wasapi-loopback:default", "hdmi", channel_map=MAP)
    assert backend.active_sessions["wasapi-loopback:default"] == ("hdmi", "headphones")
    assert bridge.matrices[-1][-1].endswith("\n0")


@pytest.mark.parametrize(
    "mapping",
    [
        None,
        {},
        [[0, 1]],
        [{"source": True, "destination": 0, "gain": 1}],
        [{"source": -1, "destination": 0, "gain": 1}],
        [{"source": 0, "destination": 64, "gain": 1}],
        [{"source": 0, "destination": 0, "gain": float("nan")}],
        [{"source": 0, "destination": 0, "gain": float("inf")}],
        [{"source": 0, "destination": 0, "gain": True}],
        [{"source": 0, "destination": 0, "gain": 4.1}],
        [{"source": 0, "destination": 0, "gain": 1}] * 2,
    ],
)
def test_invalid_matrices_rejected(mapping):
    with pytest.raises(BackendError):
        validate_channel_map(mapping)


def test_matrix_range_backend_capability_and_feedback():
    backend = WindowsBackend(MatrixBridge())
    backend.refresh()
    with pytest.raises(BackendError, match="channel index"):
        backend.create_route(
            "wasapi-loopback:default", "hdmi", channel_map=[{"source": 2, "destination": 0, "gain": 1}]
        )
    backend = WindowsBackend(DelayBridge())
    backend.refresh()
    with pytest.raises(BackendError, match="unavailable"):
        backend.create_route("wasapi-loopback:default", "hdmi", channel_map=MAP)
    with pytest.raises(BackendError, match="Feedback"):
        other = MockBackend()
        other.create_route("speakers.monitor", "speakers", channel_map=MAP)


def test_profile_aliases_and_invalid_matrix_preserve_file(tmp_path):
    backend = MockBackend()
    backend.endpoint_aliases["speakers"] = "Living room"
    backend.create_route("mic", "headphones", monitoring_confirmed=True, channel_map=MAP)
    controller = Controller(backend)
    path = tmp_path / "profile.json"
    controller.save(path)
    original = path.read_bytes()
    data = storage.load(path)
    data["routes"][0]["channel_map"][0]["gain"] = float("nan")
    with pytest.raises(BackendError):
        storage.save(path, data)
    assert path.read_bytes() == original
    restored = MockBackend()
    Controller(restored).load(path)
    assert restored.endpoint_aliases == {"speakers": "Living room"}
    assert restored.list_routes()[0].channel_map == MAP
    copied = deepcopy(MAP)
    fresh = MockBackend()
    route = fresh.create_route("mic", "headphones", monitoring_confirmed=True, channel_map=copied)
    copied.clear()
    assert route.channel_map == MAP


def test_cable_reuse_alias_and_uninstall_guard(monkeypatch):
    from a2router.backends import windows_vbcable

    def forbidden():
        raise AssertionError("Existing cable must not trigger installation")

    monkeypatch.setattr(windows_vbcable, "install", forbidden)
    backend = WindowsBackend(CableBridge())
    backend.refresh()
    assert backend.configure_cable("Music") == "Virtual output ready."
    assert not any(d.name == "Music" for d in backend.list_devices())
    assert not backend.endpoint_aliases
    assert not backend.virtual_devices
    backend.create_route("cable-out", "headphones")
    with pytest.raises(BackendError, match="Remove routes"):
        backend.uninstall_virtual_driver()
    with pytest.raises(BackendError, match="display name"):
        backend.configure_cable("")


def test_cable_create_installs_only_on_explicit_action_and_refreshes(monkeypatch):
    import json

    from test_windows import Bridge

    from a2router.backends import windows_vbcable

    class OnDemandBridge(Bridge):
        installed = False

        def ar_devices(self):
            if self.installed:
                return CableBridge().ar_devices()
            return super().ar_devices()

    bridge = OnDemandBridge()
    backend = WindowsBackend(bridge)
    calls = []

    def install():
        calls.append("install")
        bridge.installed = True
        return 0

    monkeypatch.setattr(windows_vbcable, "install", install)
    backend.refresh()
    Controller(backend).refresh()
    assert not calls
    assert backend.configure_cable("Applications") == "Virtual output ready."
    assert calls == ["install"]
    assert not any(d.name == "Applications" for d in backend.list_devices())
    assert not backend.endpoint_aliases
    backend.configure_cable("Music")
    assert calls == ["install"]
    assert len(json.loads(bridge.ar_devices())) > 5


def test_pending_restart_is_reported_but_ready_endpoint_is_available(monkeypatch):
    from test_windows import Bridge

    from a2router.backends import windows_vbcable

    class InstallingBridge(Bridge):
        installed = False

        def ar_devices(self):
            return CableBridge().ar_devices() if self.installed else super().ar_devices()

    bridge = InstallingBridge()
    backend = WindowsBackend(bridge)

    def install():
        bridge.installed = True
        return 3010

    monkeypatch.setattr(windows_vbcable, "install", install)
    assert "restart pending" in backend.configure_cable("Bus")
    assert backend._cable_outputs()


@pytest.mark.parametrize("layout", ["5.1", "7.1"])
def test_downmix_uses_positions_excludes_lfe_and_has_headroom(layout):
    from a2router.channels import conversion_preset
    from a2router.models import LAYOUTS

    source = LAYOUTS[layout]
    mapping = conversion_preset("Downmix to stereo", source, LAYOUTS["stereo"])
    assert source.index("lfe") not in {c["source"] for c in mapping}
    assert {c["source"] for c in mapping} == set(range(len(source))) - {source.index("lfe")}
    for channel in (0, 1):
        assert sum(c["gain"] for c in mapping if c["destination"] == channel) <= 1.00000001
    # Channel ordering is derived from labels rather than fixed Windows/Linux indices.
    reordered = tuple(reversed(source))
    reverse = conversion_preset("Downmix to stereo", reordered, LAYOUTS["stereo"])
    assert {(source[c["source"]], c["destination"]): c["gain"] for c in mapping} == {
        (reordered[c["source"]], c["destination"]): c["gain"] for c in reverse
    }


def test_upmix_and_mono_downmix_are_explicit():
    from a2router.channels import conversion_preset
    from a2router.models import LAYOUTS

    mapping = conversion_preset("Upmix stereo → surround", LAYOUTS["stereo"], LAYOUTS["7.1"])
    assert LAYOUTS["7.1"].index("lfe") not in {c["destination"] for c in mapping}
    center = LAYOUTS["7.1"].index("front-center")
    assert sum(c["gain"] for c in mapping if c["destination"] == center) == 1
    mono = conversion_preset("Downmix to mono", LAYOUTS["5.1"], LAYOUTS["mono"])
    assert sum(c["gain"] for c in mono) == pytest.approx(1)
    with pytest.raises(BackendError, match="Unknown source"):
        conversion_preset("Downmix to stereo", ["channel-1", "channel-2"], LAYOUTS["stereo"])
