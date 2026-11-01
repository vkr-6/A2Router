"""Owned native PipeWire port links: application copies and live unity matrices."""

import json
import os
import socket
import struct
import time
from collections import defaultdict
from pathlib import Path

from a2router.models import BackendError, Device

CHANNELS = dict(
    zip(
        (
            "MONO",
            "FL",
            "FR",
            "FC",
            "LFE",
            "RL",
            "RR",
            "FLC",
            "FRC",
            "RC",
            "SL",
            "SR",
            "TC",
            "TFL",
            "TFC",
            "TFR",
            "TRL",
            "TRC",
            "TRR",
        ),
        (
            "mono",
            "front-left",
            "front-right",
            "front-center",
            "lfe",
            "rear-left",
            "rear-right",
            "front-left-of-center",
            "front-right-of-center",
            "rear-center",
            "side-left",
            "side-right",
            "top-center",
            "top-front-left",
            "top-front-center",
            "top-front-right",
            "top-rear-left",
            "top-rear-center",
            "top-rear-right",
        ),
    )
)


def props(obj):
    return obj.get("info", {}).get("props", {})


class PipeWireGraph:
    def __init__(self, runner, owner):
        self.runner, self.owner = runner, owner
        self.objects = []
        self.nodes, self.ports, self.links = {}, {}, []

    def refresh(self):
        try:
            objects = json.loads(self.runner(["pw-dump"]))
            if not isinstance(objects, list):
                raise TypeError("Expected a graph object list")
            self.objects = objects
            self.nodes = {o["id"]: o for o in objects if o.get("type") == "PipeWire:Interface:Node"}
            self.ports = {o["id"]: o for o in objects if o.get("type") == "PipeWire:Interface:Port"}
            self.links = [o for o in objects if o.get("type") == "PipeWire:Interface:Link"]
        except (ValueError, KeyError, TypeError) as exc:
            raise BackendError(f"Invalid PipeWire graph: {exc}") from exc

    @staticmethod
    def _pulse_peer_pid(info):
        address = info.get("server_string", "")
        if not address.startswith("unix:"):
            raise BackendError("Application/channel copies require a local Unix PipeWire-Pulse socket")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(1)
                connection.connect(address[5:])
                return struct.unpack(
                    "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                )[0]
        except OSError as exc:
            raise BackendError(f"Cannot verify the Pulse server session: {exc}") from exc

    def verify_server(self, info):
        peer = self._pulse_peer_pid(info)
        if not any(
            o.get("type") == "PipeWire:Interface:Client"
            and str(props(o).get("pipewire.sec.pid")) == str(peer)
            for o in self.objects
        ):
            raise BackendError(
                "Pulse and native PipeWire tools refer to different sessions; align PULSE_SERVER and PIPEWIRE_REMOTE"
            )

    def node_ports(self, node, direction):
        ports = [
            p
            for p in self.ports.values()
            if str(props(p).get("node.id")) == str(node)
            and p.get("info", {}).get("direction") == direction
            and props(p).get("audio.channel")
        ]
        return sorted(ports, key=lambda p: int(props(p).get("port.id", p["id"])))

    @staticmethod
    def positions(ports):
        return tuple(
            CHANNELS.get(props(p)["audio.channel"], str(props(p)["audio.channel"]).lower()) for p in ports
        )

    def applications(self):
        clients = {o["id"]: props(o) for o in self.objects if o.get("type") == "PipeWire:Interface:Client"}
        groups = defaultdict(list)
        for node in self.nodes.values():
            p = {**clients.get(props(node).get("client.id"), {}), **props(node)}
            if p.get("media.class") != "Stream/Output/Audio" or p.get("a2router.owner"):
                continue
            binary = p.get("application.process.binary")
            if not binary or str(p.get("application.process.id")) == str(os.getpid()):
                continue
            pid = str(p.get("application.process.id", ""))
            identity = str(binary)
            if pid.isdecimal():
                try:
                    image = os.readlink(f"/proc/{pid}/exe")
                    if image.endswith(" (deleted)") and not Path(image).exists():
                        image = image.removesuffix(" (deleted)")
                    identity = image
                except OSError:
                    pass
            groups[identity].append((node, p))
        devices = {}
        for identity, entries in groups.items():
            ports = self.node_ports(entries[0][0]["id"], "output")
            positions = self.positions(ports)
            if not positions or len(set(positions)) != len(positions):
                continue
            p = entries[0][1]
            ident = "pw-application:" + identity
            rate = str(p.get("audio.rate", ""))
            devices[ident] = Device(
                ident,
                f"{p.get('application.name', Path(identity).name)} · application copy",
                "input",
                True,
                channels=len(positions),
                positions=positions,
                sample_rate=int(rate) if rate.isdecimal() else None,
                sample_format=p.get("audio.format"),
                state="AVAILABLE",
                properties={
                    "application_capture": True,
                    "application_path": identity,
                    "pipewire_nodes": [n[0]["id"] for n in entries],
                    "processing": "Native graph copy; original application output remains connected",
                },
            )
        return devices

    def device_node(self, device):
        serial = device.properties.get("object.serial")
        name = device.properties.get("node.name", device.id.split(":", 1)[-1].removesuffix(".monitor"))
        matches = [
            n
            for n in self.nodes.values()
            if (
                str(props(n).get("object.serial")) == str(serial)
                if serial is not None
                else props(n).get("node.name") == name
            )
        ]
        if len(matches) != 1:
            raise BackendError("PipeWire endpoint identity is missing or ambiguous")
        return matches[0]["id"]

    def desired(self, route, devices):
        source, dest = devices[route.source_id], devices[route.destination_id]
        outputs = self.node_ports(self.device_node(dest), "input")
        output_positions = self.positions(outputs)
        if len(set(output_positions)) != len(output_positions):
            raise BackendError("Ambiguous destination audio ports")
        destination_ports = []
        for position in dest.positions:
            if position not in output_positions:
                raise BackendError("Destination channel ports are unavailable")
            destination_ports.append(outputs[output_positions.index(position)])
        source_nodes = source.properties.get("pipewire_nodes") or [self.device_node(source)]
        mapping = route.channel_map or [
            {"source": i, "destination": i, "gain": 1} for i in range(source.channels or 0)
        ]
        desired = {}
        for node in source_nodes:
            inputs = self.node_ports(node, "output")
            positions = self.positions(inputs)
            if len(set(positions)) != len(positions) or set(positions) != set(source.positions):
                raise BackendError("Application streams have incompatible channel layouts")
            source_ports = [inputs[positions.index(p)] for p in source.positions]
            for connection in mapping:
                if connection["gain"] != 1:
                    raise BackendError(
                        "Native port links support unity gain; per-link gain DSP is unavailable"
                    )
                left, right = source_ports[connection["source"]], destination_ports[connection["destination"]]
                serials = (props(left).get("object.serial"), props(right).get("object.serial"))
                if any(serial is None for serial in serials):
                    raise BackendError("Stable audio-port identities are unavailable; update PipeWire")
                desired[(left["id"], right["id"])] = serials
        if not desired:
            raise BackendError("No application audio ports are available")
        return desired

    @staticmethod
    def pair(link):
        info = link.get("info", {})
        return info.get("output-port-id"), info.get("input-port-id")

    def owned(self, route_id=None):
        return [
            link
            for link in self.links
            if props(link).get("a2router.owner") == self.owner
            and (route_id is None or props(link).get("a2router.route") == route_id)
        ]

    @staticmethod
    def resource(link):
        return f"link:{link['id']}:{props(link).get('object.serial')}"

    def remove(self, link):
        self.refresh()
        if any(x["id"] == link["id"] and props(x) == props(link) for x in self.owned()):
            self.runner(["pw-link", "-d", str(link["id"])])
        self.refresh()
        if any(self.resource(x) == self.resource(link) for x in self.owned()):
            raise BackendError("Owned PipeWire link removal was not verified")

    def disconnect(self, route_id=None):
        self.refresh()
        for link in list(self.owned(route_id)):
            self.remove(link)

    def healthy(self, route, devices):
        try:
            wanted = set(self.desired(route, devices))
            links = self.owned(route.id)
            return (
                bool(wanted)
                and len(links) == len(wanted)
                and {self.pair(x) for x in links} == wanted
                and all(x.get("info", {}).get("state") in ("active", "paused") for x in links)
            )
        except (BackendError, KeyError):
            return False

    def connect(self, route, devices):
        self.refresh()
        wanted = self.desired(route, devices)
        try:
            for link in list(self.owned(route.id)):
                if self.pair(link) not in wanted:
                    self.remove(link)
            for pair, serials in wanted.items():
                self.refresh()
                if tuple(props(self.ports.get(p, {})).get("object.serial") for p in pair) != serials:
                    raise BackendError("Audio ports changed during route creation; retry")
                existing = [x for x in self.links if self.pair(x) == pair]
                if any(
                    props(x).get("a2router.owner") != self.owner or props(x).get("a2router.route") != route.id
                    for x in existing
                ):
                    raise BackendError(
                        "Audio ports already have an unrelated connection; choose another output"
                    )
                for duplicate in existing[1:]:
                    self.remove(duplicate)
                if not existing:
                    properties = json.dumps({"a2router.owner": self.owner, "a2router.route": route.id})
                    self.runner(["pw-link", "-p", properties, str(pair[0]), str(pair[1])])
            for _ in range(20):
                self.refresh()
                if self.healthy(route, devices):
                    route.resource_ids = [self.resource(link) for link in self.owned(route.id)]
                    return
                time.sleep(0.02)
            raise BackendError("PipeWire did not verify every requested channel link")
        except BackendError:
            self.disconnect(route.id)
            raise
