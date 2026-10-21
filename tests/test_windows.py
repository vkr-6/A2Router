"""Simulated C ABI regression tests; real native tests are separate."""

import json

import pytest

from a2router.backends.windows import WindowsBackend
from a2router.models import BackendError


class Bridge:
    def __init__(self):
        self.sessions = {}
        self.starts = []
        self.missing = set()
        self.fail_source = None

    def ar_devices(self):
        return json.dumps(
            [
                {
                    "id": ident,
                    "name": ident,
                    "kind": "input" if ident.startswith("mic") else "output",
                    "default": ident in ("default", "mic"),
                    "positions": ["front-left", "front-right"],
                    "channels": 2,
                    "sample_rate": 48000,
                }
                for ident in ("default", "headphones", "hdmi", "mic", "mic2")
                if ident not in self.missing
            ]
        ).encode()

    def ar_source_start(self, source, capture_input, ids):
        self.starts.append((source, capture_input, ids.splitlines()))
        if source == self.fail_source:
            self.sessions.pop(source, None)
            return 0
        if not ids:
            self.sessions.pop(source, None)
        else:
            self.sessions[source] = {
                "source_id": source,
                "capture_from_input": bool(capture_input),
                "running": True,
                "devices": [{"id": ident, "running": True, "faulted": False} for ident in ids.splitlines()],
            }
        return 1

    def ar_error(self):
        return b"simulated native startup failure"

    def ar_stats(self):
        return json.dumps({"running": bool(self.sessions), "sessions": list(self.sessions.values())}).encode()

    def ar_close(self):
        self.sessions.clear()


def test_fanout_input_capture_and_server_mixing_simulated():
    bridge = Bridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    assert backend.get_device("mic").kind == "input"
    assert backend.get_device("wasapi-loopback:headphones").monitor_of == "headphones"
    assert not backend.capabilities()["virtual_devices"]
    routes = [backend.create_route("wasapi-loopback:default", dest) for dest in ("headphones", "hdmi")]
    routes += [
        backend.create_route(source, "headphones", monitoring_confirmed=True) for source in ("mic", "mic2")
    ]
    assert all(r.status == "connected" for r in routes)
    assert len(bridge.sessions) == 3
    assert backend.active_sessions["wasapi-loopback:default"] == ("hdmi", "headphones")
    before = len(bridge.starts)
    backend.refresh()
    assert len(bridge.starts) == before
    backend.disable_route(routes[0].id)
    assert backend.active_sessions["wasapi-loopback:default"] == ("hdmi",)
    assert len(bridge.sessions) == 3  # Other source sessions keep running.
    backend.close()
    assert not bridge.sessions


def test_input_confirmation_and_nondefault_loopback():
    backend = WindowsBackend(Bridge())
    backend.refresh()
    with pytest.raises(BackendError, match="confirmation"):
        backend.create_route("mic", "headphones")
    route = backend.create_route("wasapi-loopback:headphones", "hdmi")
    assert route.status == "connected"
    with pytest.raises(BackendError, match="Feedback"):
        backend.create_route("wasapi-loopback:headphones", "headphones")


def test_hotplug_and_recovery():
    bridge = Bridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    route = backend.create_route("mic", "headphones", monitoring_confirmed=True)
    bridge.missing.add("headphones")
    backend.refresh()
    assert route.enabled and route.status == "pending"
    assert not bridge.sessions
    bridge.missing.clear()
    backend.refresh()
    assert route.status == "connected"
    assert len(bridge.sessions) == 1


def test_partial_source_failure_keeps_other_sources_running():
    bridge = Bridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    good = backend.create_route("wasapi-loopback:default", "headphones")
    bridge.fail_source = "mic"
    bad = backend.create_route("mic", "headphones", monitoring_confirmed=True)
    assert bad.status == "error" and not bad.resource_ids
    assert good.status == "connected" and "default" in bridge.sessions
    bridge.fail_source = None
    backend.refresh()
    assert bad.status == "connected"


def test_readonly_refresh_does_not_create_sessions():
    bridge = Bridge()
    backend = WindowsBackend(bridge)
    backend.refresh(reconcile=False)
    assert not bridge.starts


def test_windows_mono_duplication_policy():
    backend = WindowsBackend(Bridge())
    backend.refresh()
    backend.devices["mic"].channels = 1
    backend.devices["mic"].positions = ("mono",)
    assert backend.create_route("mic", "headphones", monitoring_confirmed=True).status == "connected"
    backend.devices["mic2"].positions = (
        "front-left",
        "front-right",
        "front-center",
        "lfe",
        "rear-left",
        "rear-right",
    )
    with pytest.raises(BackendError, match="layouts"):
        backend.create_route("mic2", "headphones", monitoring_confirmed=True)


def test_frozen_library_path(monkeypatch, tmp_path):
    from a2router.backends import windows

    monkeypatch.delenv("A2ROUTER_WASAPI_DLL", raising=False)
    monkeypatch.setattr(windows.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert windows.library_path() == tmp_path / "a2router_wasapi.dll"
    override = tmp_path / "custom.dll"
    monkeypatch.setenv("A2ROUTER_WASAPI_DLL", str(override))
    assert windows.library_path() == override
