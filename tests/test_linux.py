import json
from uuid import uuid4

import pytest

from a2router.backends.linux_pipewire import PipeWireBackend
from a2router.models import BackendError, VirtualDevice


class Server:
    def __init__(self):
        self.modules = []
        self.sinks = [self.device("sink", 1)]
        self.sources = [self.device("sink.monitor", 2), self.device("mic", 3)]
        self.sinks[0]["monitor_source"] = "sink.monitor"
        self.inputs, self.outputs = [], []
        self.commands = []
        self.fail = False

    @staticmethod
    def device(name, index):
        return {
            "index": index,
            "name": name,
            "description": name,
            "state": "IDLE",
            "sample_specification": "float32le 2ch 48000Hz",
            "channel_map": "front-left,front-right",
            "properties": {"device.api": "alsa"},
        }

    def __call__(self, args):
        self.commands.append(args)
        if self.fail:
            raise BackendError("server down")
        if args == ["-f", "json", "info"]:
            return json.dumps({"server_name": "PulseAudio (on PipeWire 1.0.5)", "default_sink_name": "sink"})
        if args[:3] == ["-f", "json", "list"]:
            return json.dumps(
                {
                    "sinks": self.sinks,
                    "sources": self.sources,
                    "modules": self.modules,
                    "sink-inputs": self.inputs,
                    "source-outputs": self.outputs,
                }[args[3]]
            )
        if args[0] == "unload-module":
            self.modules = [m for m in self.modules if str(m["index"]) != args[1]]
            self.inputs = [s for s in self.inputs if str(s["owner_module"]) != args[1]]
            self.outputs = [s for s in self.outputs if str(s["owner_module"]) != args[1]]
            return ""
        raise BackendError("unexpected command")


@pytest.fixture
def server():
    return Server()


def test_real_parser(server):
    backend = PipeWireBackend(server, owner="test")
    backend.refresh()
    assert backend.last_error == ""
    assert backend.devices["sink:sink"].default
    assert backend.devices["sink:sink"].virtual is False
    assert backend.devices["source:sink.monitor"].monitor_of == "sink:sink"
    assert backend.devices["source:mic"].kind == "input"
    assert backend.devices["sink:sink"].sample_rate == 48000
    assert backend.devices["sink:sink"].sample_format == "float32le"
    assert backend.devices["sink:sink"].latency == {}


def test_unavailable_and_corrupt_server(server):
    backend = PipeWireBackend(server)
    server.fail = True
    backend.refresh()
    assert not backend.diagnostics()["available"]
    assert not backend.devices
    invalid = PipeWireBackend(lambda _: "not JSON")
    invalid.refresh()
    assert "invalid JSON" in invalid.last_error


def test_ownership_stale_ids_and_cleanup(server):
    ident = str(uuid4())
    backend = PipeWireBackend(server, owner="test")
    server.modules = [
        {
            "index": 10,
            "name": "module-loopback",
            "argument": f'sink_input_properties="a2router.owner=test a2router.route={ident}"',
        },
        {
            "index": 11,
            "name": "module-loopback",
            "argument": 'sink_input_properties="a2router.owner=other a2router.route=other"',
        },
        {"index": 12, "name": "module-null-sink", "argument": "sink_name=users_sink"},
    ]
    backend.refresh()
    assert backend.stale_resources == ["10"]
    backend._unload("route", ident)
    assert [m["index"] for m in server.modules] == [11, 12]
    # Numeric ID reused by an unrelated module must not be unloaded.
    server.modules.append({"index": 10, "name": "module-loopback", "argument": "source=mic sink=sink"})
    backend._unload("route", ident)
    assert len(server.modules) == 3
    backend.cleanup_owned()
    assert len(server.modules) == 3


def test_creation_partial_failure_rolls_back(server, monkeypatch):
    backend = PipeWireBackend(server, owner="test")
    v = VirtualDevice("bus")
    original = server.__call__

    def runner(args):
        if args[0] == "load-module":
            server.modules.append(
                {
                    "index": 20,
                    "name": "module-null-sink",
                    "argument": f'sink_properties="a2router.owner=test a2router.virtual={v.id}"',
                }
            )
            return "20"  # Endpoint intentionally never appears.
        return original(args)

    backend.runner = runner
    monkeypatch.setattr("a2router.backends.linux_pipewire.time.sleep", lambda _: None)
    backend.refresh()
    with pytest.raises(BackendError, match="rolled back"):
        backend.create_virtual_device(v)
    assert server.modules == [] and backend.virtual_devices == {}


def test_verified_route_reconciliation(server):
    backend = PipeWireBackend(server, owner="test")
    backend.refresh()
    ident = str(uuid4())
    # Adopt a verified owned module on restart rather than create duplicates.
    server.modules.append(
        {
            "index": 20,
            "name": "module-loopback",
            "argument": f'sink_input_properties="a2router.owner=test a2router.route={ident}"',
        }
    )
    server.inputs.append({"owner_module": 20, "sink": 1})
    server.outputs.append({"owner_module": 20, "source": 3})
    backend.refresh()
    route = backend.create_route("source:mic", "sink:sink", route_id=ident, monitoring_confirmed=True)
    assert route.status == "connected" and route.resource_ids == ["20"]
    backend.refresh()
    assert not any(cmd[0] == "load-module" for cmd in server.commands)
    backend.disable_route(ident)
    backend.disable_route(ident)
    assert not server.modules
    assert route.status == "disabled"


def test_source_destination_wrong_layout(server):
    backend = PipeWireBackend(server)
    server.sources[1]["channel_map"] = "mono"
    backend.refresh()
    with pytest.raises(BackendError, match="layouts"):
        backend.create_route("source:mic", "sink:sink", monitoring_confirmed=True)


def test_modules_json_without_indices(server):
    ident = str(uuid4())
    module = {
        "index": 20,
        "name": "module-loopback",
        "argument": f'sink_input_properties="a2router.owner=test a2router.route={ident}"',
    }
    server.modules.append(module)

    def runner(args):
        if args == ["-f", "json", "list", "modules"]:
            return json.dumps([{k: v for k, v in module.items() if k != "index"}])
        if args == ["list", "short", "modules"]:
            return f"20\tmodule-loopback\t{module['argument']}\tn/a"
        return server(args)

    backend = PipeWireBackend(runner, owner="test")
    backend.refresh()
    assert backend.last_error == ""
    assert backend.stale_resources == ["20"]


def test_inspection_does_not_create_missing_resources(server):
    from dataclasses import asdict

    from a2router.controller import Controller
    from a2router.models import Route

    backend = PipeWireBackend(server)
    data = {
        "version": 1,
        "virtual_devices": [asdict(VirtualDevice("pending"))],
        "routes": [asdict(Route("source:mic", "sink:sink", monitoring_confirmed=True))],
    }
    for key in ("status", "error", "resource_ids"):
        data["routes"][0].pop(key)
    assert Controller(backend).restore(data, activate=False) == []
    assert backend.list_routes()[0].status == "pending"
    assert not any(cmd[0] in ("load-module", "unload-module") for cmd in server.commands)


def test_rollback_verifies_exact_request_when_server_loses_property_tags(server, monkeypatch):
    backend = PipeWireBackend(server, owner="test")
    original = server.__call__

    def runner(args):
        if args[0] == "load-module":
            server.modules.append({"index": 22, "name": args[1], "argument": " ".join(args[2:])})
            return "22"
        return original(args)

    backend.runner = runner
    monkeypatch.setattr(backend, "_owned", lambda *_: False)
    monkeypatch.setattr("a2router.backends.linux_pipewire.time.sleep", lambda _: None)
    backend.refresh()
    with pytest.raises(BackendError, match="rolled back"):
        backend.create_virtual_device(VirtualDevice("parser failure"))
    assert not server.modules and not backend.virtual_devices


def test_device_master_controls_use_native_server_commands(server):
    server.sinks[0]["volume"] = {"front-left": {"value": 49152}, "front-right": {"value": 49152}}
    server.sinks[0]["mute"] = False
    calls = []

    def runner(args):
        if args[0] == "set-sink-volume":
            calls.append(args)
            value = int(args[2])
            server.sinks[0]["volume"] = {"front-left": {"value": value}, "front-right": {"value": value}}
            return ""
        if args[0] == "set-source-mute":
            calls.append(args)
            server.sources[1]["mute"] = args[2] == "1"
            return ""
        return server(args)

    backend = PipeWireBackend(runner)
    backend.refresh()
    assert backend.get_device("sink:sink").properties["controls"]["volume"] == 0.75
    backend.set_device_volume("sink:sink", 0.4)
    backend.set_device_mute("source:mic", True)
    assert calls == [["set-sink-volume", "sink", "26214"], ["set-source-mute", "mic", "1"]]
    assert backend.get_device("source:mic").properties["controls"]["muted"] is True
    assert not backend.capabilities()["meters"]


@pytest.mark.parametrize("name", ["My audio output", "User's output", 'Output "A"'])
def test_legacy_sink_description_uses_one_quote_level(server, name):
    backend = PipeWireBackend(server, owner="test")
    backend.refresh()
    backend.server["server_name"] = "PulseAudio (on PipeWire 0.3.48)"
    config = VirtualDevice(name)
    requests = []

    def load(module_name, args, kind, ident, verify):
        requests.append(args)
        return "20"

    backend._load = load
    backend._create_virtual(config)
    args = requests[0]
    description = next(arg.partition("=")[2] for arg in args if arg.startswith("device.description="))
    assert description[1:-1] == name
    assert description[0] == description[-1] and description[0] not in name
    properties = next(arg for arg in args if arg.startswith("sink_properties="))
    assert "device.description" not in properties
    assert "a2router.owner=test" in properties and config.id in properties


@pytest.mark.parametrize("name", ["Both ' and \" quotes", "Back\\slash", "Ending\\"])
def test_legacy_unrepresentable_names_fail_before_module_creation(server, name):
    backend = PipeWireBackend(server, owner="test")
    backend.refresh()
    backend.server["server_name"] = "PulseAudio (on PipeWire 0.3.48)"
    with pytest.raises(BackendError, match="simpler name"):
        backend.create_virtual_device(VirtualDevice(name))
    assert not backend.virtual_devices
    assert not any(cmd[0] == "load-module" for cmd in server.commands)


def test_legacy_parser_detection_does_not_change_other_servers(server):
    backend = PipeWireBackend(server)
    for name in ("PulseAudio", "PulseAudio (on PipeWire 1.0.5)", "PulseAudio (on PipeWire 0.3.80)"):
        backend.server = {"server_name": name}
        assert not backend._legacy_property_parser()
    backend.server = {"server_name": "PulseAudio (on PipeWire 0.3.48)"}
    assert backend._legacy_property_parser()


def test_classic_pulse_matrix_plan_and_gain_validation(server):
    from a2router.models import Route

    def pulse(args):
        if args == ["-f", "json", "info"]:
            return json.dumps({"server_name": "pulseaudio", "default_sink_name": "sink"})
        return server(args)

    backend = PipeWireBackend(pulse, owner="test")
    backend.refresh()
    assert backend.capabilities()["channel_routing"]
    assert not backend.capabilities()["live_channel_routing"]
    route = Route(
        "source:mic",
        "sink:sink",
        monitoring_confirmed=True,
        channel_map=[
            {"source": 0, "destination": 0, "gain": 1},
            {"source": 1, "destination": 1, "gain": 1},
        ],
    )
    plan = backend.pulse_matrix.plan(route)
    assert len(plan) == 2 and plan == backend.pulse_matrix.plan(route)
    assert plan[0][2] == "module-remap-sink"
    for _, part, module, args, *_ in plan:
        resource = {"name": module, "argument": " ".join(args)}
        assert backend._owned(resource, "matrix", route.id)
        assert backend._owned(resource, "part", part)
    route.channel_map[1] = {"source": 0, "destination": 1, "gain": 1}
    assert len(backend.pulse_matrix.plan(route)) == 4
    route.channel_map[0]["gain"] = 0.5
    with pytest.raises(BackendError, match="unity gain"):
        backend._validate_route(route)
    assert not server.modules


def test_pulse_property_ownership_handles_escaped_apostrophes(server):
    backend = PipeWireBackend(server, owner="test")
    backend.server = {"server_name": "pulseaudio"}
    ident = str(uuid4())
    properties = "device.description=\"A 'quoted' cable\" a2router.owner=test a2router.virtual=" + ident
    module = {
        "name": "module-null-sink",
        "argument": "sink_properties=" + backend._property_argument(properties),
    }
    assert backend._owned(module, "virtual", ident)
    assert not PipeWireBackend(server, owner="other")._owned(module)


def test_owned_matrix_cleanup_ignores_mutable_usage_counters(server):
    ident = str(uuid4())
    props = f"a2router.owner=test a2router.matrix={ident}"
    server.modules = [
        {"index": 20, "name": "module-remap-sink", "argument": f"sink_properties='{props}'"},
        {"index": 21, "name": "module-loopback", "argument": f"sink_input_properties='{props}'"},
        {"index": 22, "name": "module-remap-sink", "argument": "master=users_output"},
    ]
    reads = []

    def changing_usage(args):
        if args == ["-f", "json", "list", "modules"]:
            reads.append(args)
            return json.dumps([{**m, "usage_counter": len(reads)} for m in server.modules])
        return server(args)

    backend = PipeWireBackend(changing_usage, owner="test")
    backend.server = {"server_name": "pulseaudio"}
    backend._unload("matrix", ident)
    assert [m["index"] for m in server.modules] == [22]
