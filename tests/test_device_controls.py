"""Control and configuration simulations; these never modify Windows endpoints."""

import json

import pytest
from test_windows import CableBridge

from a2router.backends.windows import WindowsBackend
from a2router.models import BackendError

FORMATS = [
    {"channels": channels, "sample_rate": 48000, "bits": 24, "container_bits": 32, "encoding": "pcm"}
    for channels in (2, 6, 8, 16)
]


class ConfigurationBridge(CableBridge):
    def __init__(self):
        super().__init__()
        self.configs = {}
        self.names = {}
        self.volume = 0.8
        self.muted = False
        self.format_calls = []
        self.reject_format = False

    def ar_devices(self):
        rows = json.loads(super().ar_devices())
        for row in rows:
            if row["id"].startswith("cable-"):
                # Reproduce the reported bug: a genuine endpoint is enumerated
                # but not tagged virtual until adapter branding is considered.
                row["properties"] = {"interface_name": "VB-Audio Virtual Cable"}
                config = self.configs.get(row["id"], FORMATS[0])
                row.update(
                    channels=config["channels"],
                    sample_rate=config["sample_rate"],
                    positions=["front-left", "front-right"]
                    if config["channels"] == 2
                    else [f"channel-{i + 1}" for i in range(config["channels"])],
                )
                row["properties"]["device_format"] = config
                row["properties"]["controls"] = self.controls()
                row["name"] = self.names.get(row["id"], row["name"])
        return json.dumps(rows).encode()

    def controls(self):
        return {
            "volume_available": True,
            "volume": self.volume,
            "muted": self.muted,
            "peak_available": True,
            "peak": 0.25,
        }

    def ar_controls(self):
        return json.dumps(
            [{"id": ident, "controls": self.controls()} for ident in ("cable-in", "cable-out", "cable-16")]
        ).encode()

    def ar_set_device_volume(self, ident, level):
        self.volume = level
        return 1

    def ar_set_device_mute(self, ident, muted):
        self.muted = bool(muted)
        return 1

    def ar_device_formats(self, ident):
        return json.dumps(FORMATS).encode()

    def ar_set_device_format(self, ident, channels, rate, bits, floating, container):
        self.format_calls.append((ident, channels, rate, bits, floating, container))
        if self.reject_format:
            return 0
        self.configs[ident] = {
            "channels": channels,
            "sample_rate": rate,
            "bits": bits,
            "encoding": "float" if floating else "pcm",
            "container_bits": container,
        }
        return 1

    def ar_rename_device(self, ident, name):
        self.names[ident] = name
        return 1


@pytest.mark.parametrize("adapter_name", ["VB-Audio Virtual Cable", "VB-Audio Point"])
def test_adapter_branding_classifies_existing_endpoints_without_installing(monkeypatch, adapter_name):
    from a2router.backends import windows_vbcable

    monkeypatch.setattr(
        windows_vbcable, "install", lambda: pytest.fail("An existing cable must never be reinstalled")
    )
    bridge = ConfigurationBridge()
    original = bridge.ar_devices
    bridge.ar_devices = lambda: original().replace(b"VB-Audio Virtual Cable", adapter_name.encode())
    backend = WindowsBackend(bridge)
    backend.refresh()
    assert len(backend._cable_outputs()) == 2
    assert backend.get_device("cable-out").properties["capture_endpoint_id"] == "cable-out"
    assert backend.get_device("cable-in").virtual is True
    assert backend.configure_cable("Bus") == "Virtual output ready."
    with pytest.raises(BackendError, match="Feedback"):
        backend.create_route("cable-out", "cable-16")


def test_device_controls_are_verified_observations_and_do_not_restart_routes():
    bridge = StreamBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    backend.create_route("cable-out", "headphones")
    starts = len(bridge.starts)
    backend.set_device_volume("cable-in", 0.35)
    backend.set_device_mute("cable-in", True)
    controls = backend.get_device("cable-in").properties["controls"]
    assert controls["volume"] == 0.35 and controls["muted"] is True
    assert controls["peak"] == 0.25 and controls["observed_at"] > 0
    assert len(bridge.starts) == starts
    for value in (-0.1, 1.1, True, float("nan")):
        with pytest.raises(BackendError):
            backend.set_device_volume("cable-in", value)


def test_format_scan_apply_16_channels_and_true_system_name():
    bridge = ConfigurationBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    with pytest.raises(BackendError, match="Scan formats"):
        backend.configure_device_format("cable-out", FORMATS[-1])
    backend.inspect_formats("cable-out")
    backend.configure_device_format("cable-out", FORMATS[-1])
    assert backend.get_device("cable-out").channels == 16
    assert bridge.format_calls[-1] == ("cable-out", 16, 48000, 24, 0, 32)
    backend.endpoint_aliases["cable-in"] = "Old alias"
    backend.rename_device("cable-in", "Game bus")
    assert backend.get_device("cable-in").name == "Game bus"
    assert "cable-in" not in backend.endpoint_aliases
    assert backend.get_device("cable-in").id == "cable-in"


def test_active_routes_block_format_changes_and_rejections_preserve_state():
    bridge = ConfigurationBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    backend.inspect_formats("cable-out")
    route = backend.create_route("cable-out", "headphones")
    with pytest.raises(BackendError, match="Stop routes"):
        backend.configure_device_format("cable-out", FORMATS[-1])
    assert bridge.format_calls == []
    backend.disable_route(route.id)
    bridge.reject_format = True
    with pytest.raises(BackendError):
        backend.configure_device_format("cable-out", FORMATS[-1])
    assert backend.get_device("cable-out").channels == 2


def test_telemetry_failure_does_not_hide_working_endpoints():
    bridge = ConfigurationBridge()
    bridge.ar_stats = lambda: None
    backend = WindowsBackend(bridge)
    backend.refresh()
    assert len(backend._cable_outputs()) == 2
    assert backend.get_device("cable-out").channels == 2
    assert "telemetry" in backend.last_error.lower()


def test_shared_cable_route_blocks_alternative_pin_reconfiguration():
    backend = WindowsBackend(ConfigurationBridge())
    backend.refresh()
    backend.inspect_formats("cable-16")
    backend.create_route("cable-out", "headphones")
    with pytest.raises(BackendError, match="Stop routes"):
        backend.configure_device_format("cable-16", FORMATS[-1])


def test_gui_stop_allows_format_change_without_restarting_desired_route():
    from a2router.controller import Controller

    bridge = ConfigurationBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    route = backend.create_route("cable-out", "headphones")
    controller = Controller(backend)
    controller.pause_routes()
    controller.refresh()
    assert route.enabled and route.status == "stopped"
    assert not backend.active_sessions
    backend.inspect_formats("cable-out")
    backend.configure_device_format("cable-out", FORMATS[-1])
    assert backend.get_device("cable-out").channels == 16
    assert route.enabled and not backend.active_sessions


class StreamBridge(ConfigurationBridge):
    """Simulated stream-volume extension; not a Windows audio playback test."""

    def __init__(self):
        super().__init__()
        self.gain_calls = []
        self.reject_gain = None

    def ar_routing_controls_version(self):
        return 1

    def ar_source_start_config(self, source, capture, ids, delays, matrices, volumes):
        result = self.ar_source_start(source, capture, ids)
        if result and ids:
            for device, volume in zip(self.sessions[source]["devices"], volumes.splitlines()):
                device["volume"] = float(volume)
        return result

    def ar_source_set_volume(self, source, capture, dest, gain):
        self.gain_calls.append((source, dest, gain))
        if self.reject_gain == (dest, gain):
            return 0
        for device in self.sessions[source]["devices"]:
            if device["id"] == dest:
                device["volume"] = gain
                return 1
        return 0


def test_cable_stream_gain_is_live_shared_across_pins_and_restored_on_restart():
    from a2router.controller import Controller

    bridge = StreamBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    route = backend.create_route("cable-out", "headphones")
    starts = len(bridge.starts)
    backend.set_device_volume("cable-16", 0.3)
    assert route.volume == 0.3 and bridge.sessions["cable-out"]["devices"][0]["volume"] == 0.3
    assert len(bridge.starts) == starts and bridge.volume == 0.8
    backend.set_device_mute("cable-in", True)
    assert route.muted and bridge.sessions["cable-out"]["devices"][0]["volume"] == 0
    controller = Controller(backend)
    profile = controller.snapshot()
    controller.pause_routes()
    controller.resume_routes()
    assert bridge.sessions["cable-out"]["devices"][0]["volume"] == 0
    assert controller.snapshot() == profile
    backend.set_device_mute("cable-out", False)
    assert bridge.sessions["cable-out"]["devices"][0]["volume"] == 0.3


def test_failed_cable_gain_rolls_back_successful_outputs():
    bridge = StreamBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    first = backend.create_route("cable-out", "headphones")
    second = backend.create_route("cable-out", "hdmi")
    bridge.reject_gain = ("hdmi", 0.2)
    with pytest.raises(BackendError, match="previous gains restored"):
        backend.set_device_volume("cable-out", 0.2)
    assert first.volume == second.volume == 1
    assert all(d["volume"] == 1 for d in bridge.sessions["cable-out"]["devices"])


def test_stream_gain_stats_failure_rolls_back_native_and_desired_state():
    class InterruptedStats(StreamBridge):
        unreadable = False

        def ar_source_set_volume(self, source, capture, dest, gain):
            result = super().ar_source_set_volume(source, capture, dest, gain)
            if gain == 0.2:
                self.unreadable = True
            return result

        def ar_stats(self):
            if self.unreadable:
                self.unreadable = False
                return None
            return super().ar_stats()

    bridge = InterruptedStats()
    backend = WindowsBackend(bridge)
    backend.refresh()
    route = backend.create_route("cable-out", "headphones")
    with pytest.raises(BackendError, match="previous stream gain restored"):
        backend.set_route_volume(route.id, 0.2)
    assert route.volume == 1 and bridge.sessions["cable-out"]["devices"][0]["volume"] == 1


def test_stream_gain_waits_for_supervisor_snapshot_without_restarting():
    class DelayedStats(StreamBridge):
        stale = None
        remaining = 0

        def ar_source_set_volume(self, source, capture, dest, gain):
            self.stale = super().ar_stats()
            self.remaining = 3
            return super().ar_source_set_volume(source, capture, dest, gain)

        def ar_stats(self):
            if self.remaining:
                self.remaining -= 1
                return self.stale
            return super().ar_stats()

    bridge = DelayedStats()
    backend = WindowsBackend(bridge)
    backend.refresh()
    route = backend.create_route("cable-out", "headphones")
    starts = len(bridge.starts)
    backend.set_route_volume(route.id, 0.2)
    assert route.volume == 0.2
    assert len(bridge.gain_calls) == 1 and len(bridge.starts) == starts


def test_saved_format_with_unchanged_active_mix_reports_pending_state():
    class PendingFormat(ConfigurationBridge):
        def ar_set_device_format(self, *args):
            self.format_calls.append(args)
            return 1  # Configuration saved; active audio engine still uses stereo.

    backend = WindowsBackend(PendingFormat())
    backend.refresh()
    backend.inspect_formats("cable-out")
    message = backend.configure_device_format("cable-out", FORMATS[-1])
    assert "active mix format has not changed" in message
    assert backend.get_device("cable-out").channels == 2
