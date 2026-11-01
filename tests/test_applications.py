"""Windows application APIs are simulated; native graph integration is separate."""

import json
from copy import deepcopy

import pytest
from test_device_controls import StreamBridge

from a2router.backends.windows import WindowsBackend
from a2router.controller import Controller
from a2router.models import BackendError

APP = r"C:\Apps\Player.exe"


class ApplicationBridge(StreamBridge):
    def __init__(self):
        super().__init__()
        self.apps = [{"path": APP, "pid": 200, "stamp": "400"}]
        self.matrix_calls = []
        self.reject_matrix = False

    def ar_application_api_version(self):
        return 1

    def ar_application_capture_supported(self):
        return 1

    def ar_applications(self):
        return json.dumps(self.apps).encode()

    def ar_source_start_matrix(self, *args):
        return self.ar_source_start_config(*args, "\n".join("1" for _ in args[2].splitlines()))

    def ar_live_matrix_version(self):
        return 1

    def ar_source_set_matrix(self, source, capture, destination, matrix):
        self.matrix_calls.append((source, capture, destination, matrix))
        return 0 if self.reject_matrix else 1


def test_application_fanout_reconnect_and_stable_profile_identity():
    bridge = ApplicationBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    app = "application:" + APP.casefold()
    a = backend.create_route(app, "headphones")
    b = backend.create_route(app, "hdmi")
    assert a.status == b.status == "connected"
    assert not a.monitoring_confirmed  # A process copy is not microphone monitoring.
    profile = Controller(backend).snapshot()
    bridge.apps = []
    backend.refresh()
    assert a.status == b.status == "pending" and not bridge.sessions
    bridge.apps = [{"path": APP.upper(), "pid": 201, "stamp": "401"}]
    backend.refresh()
    assert a.status == b.status == "connected"
    assert set(bridge.sessions) == {"process:201:401"}
    assert Controller(backend).snapshot() == profile


def test_changed_process_identity_stops_previous_binding_before_new_capture():
    bridge = ApplicationBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    route = backend.create_route("application:" + APP.casefold(), "headphones")
    bridge.apps[0].update(pid=202, stamp="900")
    backend.refresh()
    assert route.status == "connected"
    assert set(bridge.sessions) == {"process:202:900"}
    assert ("process:200:400", 0, []) in bridge.starts


def test_application_discovery_failure_keeps_endpoint_routes_available():
    bridge = ApplicationBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    bridge.apps = [{"bad": "metadata"}]
    backend.refresh()
    assert backend.get_device("headphones") and backend.application_error
    assert not backend.last_error
    assert backend.create_route("wasapi-loopback:default", "headphones").status == "connected"


def test_live_matrix_edit_does_not_restart_any_output_and_failure_preserves_map():
    bridge = ApplicationBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    original = [{"source": 0, "destination": 0, "gain": 1}, {"source": 1, "destination": 1, "gain": 1}]
    route = backend.create_route("application:" + APP.casefold(), "headphones", channel_map=original)
    backend.create_route(route.source_id, "hdmi")
    starts = len(bridge.starts)
    swap = [{"source": 0, "destination": 1, "gain": 0.5}, {"source": 1, "destination": 0, "gain": 1}]
    backend.set_route_channel_map(route.id, swap)
    backend.refresh()
    assert route.channel_map == swap and len(bridge.starts) == starts
    assert len(bridge.matrix_calls) == 1
    bridge.reject_matrix = True
    with pytest.raises(BackendError):
        backend.set_route_channel_map(route.id, original)
    assert route.channel_map == swap and len(bridge.starts) == starts
    saved = deepcopy(Controller(backend).snapshot())
    assert saved["routes"][0]["channel_map"] == swap


def test_multiple_process_trees_keep_existing_binding_until_it_disappears():
    bridge = ApplicationBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    source = "application:" + APP.casefold()
    route = backend.create_route(source, "headphones")
    bridge.apps = [{"path": APP, "pid": 100, "stamp": "100"}, {"path": APP, "pid": 200, "stamp": "400"}]
    backend.refresh()
    assert backend.get_device(source).properties["pid"] == 200
    assert set(bridge.sessions) == {"process:200:400"}
    bridge.apps.pop()
    backend.refresh()
    assert route.status == "connected"
    assert set(bridge.sessions) == {"process:100:100"}


def test_existing_application_playback_output_is_not_duplicated():
    bridge = ApplicationBridge()
    bridge.apps[0]["original_outputs"] = ["headphones"]
    backend = WindowsBackend(bridge)
    backend.refresh()
    source = "application:" + APP.casefold()
    with pytest.raises(BackendError, match="already plays"):
        backend.create_route(source, "headphones")
    assert not bridge.sessions
    assert backend.create_route(source, "hdmi").status == "connected"


def test_first_matrix_on_float_stereo_application_route_is_live():
    bridge = ApplicationBridge()
    backend = WindowsBackend(bridge)
    backend.refresh()
    route = backend.create_route("application:" + APP.casefold(), "headphones")
    starts = len(bridge.starts)
    assert not route.channel_map and backend.can_live_channel_map(route.id)
    mapping = [{"source": 0, "destination": 1, "gain": 1}, {"source": 1, "destination": 0, "gain": 1}]
    backend.set_route_channel_map(route.id, mapping)
    backend.refresh()
    assert route.channel_map == mapping and len(bridge.starts) == starts
    assert bridge.matrix_calls
