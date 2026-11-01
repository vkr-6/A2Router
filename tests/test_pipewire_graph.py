"""Deterministic ownership/failure checks; no audio server or hardware is used."""

import json

import pytest

from a2router.backends.pipewire_graph import PipeWireGraph
from a2router.models import LAYOUTS, BackendError, Device, Route


def obj(kind, ident, properties, **info):
    return {
        "type": "PipeWire:Interface:" + kind,
        "id": ident,
        "info": {"props": {"object.serial": ident + 1000, **properties}, **info},
    }


class GraphServer:
    def __init__(self):
        self.objects = [
            obj(
                "Node",
                1,
                {
                    "media.class": "Stream/Output/Audio",
                    "application.process.binary": "player",
                    "application.name": "Player",
                },
            ),
            obj("Node", 2, {"node.name": "speakers"}),
        ]
        for node, direction in ((1, "output"), (2, "input")):
            for index, channel in enumerate(("FL", "FR")):
                self.objects.append(
                    obj(
                        "Port",
                        node * 100 + index,
                        {"node.id": node, "port.id": index, "audio.channel": channel},
                        direction=direction,
                    )
                )
        self.next_id = 500
        self.fail_pair = None

    def __call__(self, args):
        if args == ["pw-dump"]:
            return json.dumps(self.objects)
        if args[:2] == ["pw-link", "-p"]:
            pair = tuple(map(int, args[-2:]))
            if pair == self.fail_pair:
                raise BackendError("Injected link failure")
            self.objects.append(
                obj(
                    "Link",
                    self.next_id,
                    json.loads(args[2]),
                    **{"output-port-id": pair[0], "input-port-id": pair[1], "state": "active"},
                )
            )
            self.next_id += 1
        elif args[:2] == ["pw-link", "-d"]:
            self.objects = [x for x in self.objects if x["id"] != int(args[2])]
        else:
            raise AssertionError(args)
        return ""


def setup():
    server = GraphServer()
    graph = PipeWireGraph(server, "owner")
    graph.refresh()
    apps = graph.applications()
    devices = {
        **apps,
        "sink:speakers": Device(
            "sink:speakers",
            "Speakers",
            "output",
            channels=2,
            positions=LAYOUTS["stereo"],
            properties={"object.serial": 1002},
        ),
    }
    route = Route(next(iter(apps)), "sink:speakers")
    return server, graph, devices, route


def test_unity_mapping_live_update_and_cleanup_do_not_delete_unrelated_links():
    server, graph, devices, route = setup()
    unrelated = obj("Link", 900, {}, **{"output-port-id": 100, "input-port-id": 999, "state": "active"})
    server.objects.append(unrelated)
    graph.connect(route, devices)
    assert len(graph.owned(route.id)) == 2
    route.channel_map = [
        {"source": 0, "destination": 1, "gain": 1},
        {"source": 1, "destination": 0, "gain": 1},
    ]
    graph.connect(route, devices)
    assert {graph.pair(link) for link in graph.owned(route.id)} == {(100, 201), (101, 200)}
    graph.disconnect(route.id)
    assert unrelated in server.objects and not graph.owned()


def test_partial_link_failure_rolls_back_only_owned_resources():
    server, graph, devices, route = setup()
    server.fail_pair = (101, 201)
    with pytest.raises(BackendError, match="Injected"):
        graph.connect(route, devices)
    assert not graph.owned() and not route.resource_ids


def test_existing_unrelated_connection_is_not_adopted_or_deleted():
    server, graph, devices, route = setup()
    original = obj("Link", 900, {}, **{"output-port-id": 100, "input-port-id": 200, "state": "active"})
    server.objects.append(original)
    with pytest.raises(BackendError, match="unrelated"):
        graph.connect(route, devices)
    assert original in server.objects and not graph.owned()


def test_deleted_running_executable_keeps_application_identity(monkeypatch):
    server, graph, _, _ = setup()
    server.objects[0]["info"]["props"]["application.process.id"] = 123456
    graph.refresh()
    monkeypatch.setattr(
        "a2router.backends.pipewire_graph.os.readlink", lambda _: "/uninstalled/player (deleted)"
    )
    assert "pw-application:/uninstalled/player" in graph.applications()


def test_native_graph_must_match_the_pulse_server_session(monkeypatch):
    server, graph, _, _ = setup()
    monkeypatch.setattr(graph, "_pulse_peer_pid", lambda _: 42)
    with pytest.raises(BackendError, match="different sessions"):
        graph.verify_server({})
    server.objects.append(obj("Client", 999, {"pipewire.sec.pid": 42}))
    graph.refresh()
    graph.verify_server({})
    with pytest.raises(BackendError, match="local Unix"):
        PipeWireGraph._pulse_peer_pid({"server_string": "tcp:remote-host"})
