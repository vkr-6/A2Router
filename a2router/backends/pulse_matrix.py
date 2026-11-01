"""Channel remapping through owned PulseAudio remap-sink/loopback modules."""

import hashlib
import json
from uuid import UUID, uuid5

from a2router.channels import validate_channel_map
from a2router.models import BackendError


class PulseMatrix:
    def __init__(self, backend):
        self.backend = backend

    def plan(self, route):
        b = self.backend
        source, destination = b.get_device(route.source_id), b.get_device(route.destination_id)
        validate_channel_map(route.channel_map, source.channels, destination.channels)
        if (
            not source.positions
            or not destination.positions
            or len(set(source.positions)) != source.channels
            or len(set(destination.positions)) != destination.channels
        ):
            raise BackendError("PulseAudio mapping requires unique reported channel positions")
        if len(route.channel_map) > 64:
            raise BackendError("PulseAudio mapping supports at most 64 connections per route")
        layers = []
        # Each layer uses unique master/destination positions. Additional layers
        # implement duplication and summing using the server's normal mixer.
        for connection in sorted(route.channel_map, key=lambda c: (c["destination"], c["source"])):
            for layer in layers:
                if all(
                    c["source"] != connection["source"] and c["destination"] != connection["destination"]
                    for c in layer
                ):
                    layer.append(connection)
                    break
            else:
                layers.append([connection])
        signature = hashlib.sha256(
            json.dumps(
                [route.source_id, route.destination_id, source.positions, destination.positions, layers],
                sort_keys=True,
            ).encode()
        ).hexdigest()[:24]
        plan = []
        for i, layer in enumerate(layers):
            name = "a2router_matrix_" + route.id.replace("-", "") + f"_{i}"
            positions = ",".join(source.positions[c["source"]] for c in layer)
            master_positions = ",".join(destination.positions[c["destination"]] for c in layer)
            for kind in ("remap", "loop"):
                part = str(uuid5(UUID(route.id), f"{signature}:{i}:{kind}"))
                tags = (
                    f"a2router.owner={b.owner} a2router.matrix={route.id} a2router.part={part} "
                    "a2router.internal=matrix media.name=a2router"
                )
                if kind == "remap":
                    args = [
                        "sink_name=" + name,
                        "master=" + destination.id.removeprefix("sink:"),
                        f"channels={len(layer)}",
                        "master_channel_map=" + master_positions,
                        "channel_map=" + positions,
                        "remix=no",
                        "sink_properties=" + b._property_argument(tags),
                    ]
                    module = "module-remap-sink"
                else:
                    args = [
                        "source=" + source.id.removeprefix("source:"),
                        "sink=" + name,
                        f"channels={len(layer)}",
                        "channel_map=" + positions,
                        "remix=false",
                        "source_dont_move=true",
                        "sink_dont_move=true",
                        "sink_input_properties=" + b._property_argument(tags),
                        "source_output_properties=" + b._property_argument(tags),
                    ]
                    module = "module-loopback"
                plan.append((kind, part, module, args, name, positions))
        return plan

    def verified(self, route, entry, module):
        b = self.backend
        kind, _, expected_module, args, name, positions = entry
        if module.get("name") != expected_module or b._arguments(module) != b._arguments(
            {"argument": " ".join(args)}
        ):
            return False
        remap = next((s for s in b.raw_sinks if s.get("name") == name), None)
        if remap is None or remap.get("channel_map") != positions:
            return False
        index = str(module["index"])
        destination = b.get_device(route.destination_id).properties["server_index"]
        target = destination if kind == "remap" else remap["index"]
        if not any(
            str(s.get("owner_module")) == index and str(s.get("sink")) == str(target) for s in b.sink_inputs
        ):
            return False
        if kind == "remap":
            return str(remap.get("owner_module")) == index
        source = b.get_device(route.source_id).properties["server_index"]
        return any(
            str(s.get("owner_module")) == index and str(s.get("source")) == str(source)
            for s in b.source_outputs
        )

    def healthy(self, route):
        try:
            plan = self.plan(route)
            if len(self.backend._find("matrix", route.id)) != len(plan):
                return False
            return all(
                len(modules := self.backend._find("part", entry[1])) == 1
                and self.verified(route, entry, modules[0])
                for entry in plan
            )
        except BackendError:
            return False

    def connect(self, route):
        b = self.backend
        if not self.healthy(route):
            plan = self.plan(route)
            b._unload("matrix", route.id)
            try:
                for entry in plan:
                    _, part, module, args, _, _ = entry
                    b._load(module, args, "part", part, lambda m, e=entry: self.verified(route, e, m))
            except BackendError:
                b._unload("matrix", route.id)
                raise
        route.resource_ids = [str(m["index"]) for m in b._find("matrix", route.id)]
