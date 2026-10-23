from copy import deepcopy
from dataclasses import asdict

from a2router.channels import validate_channel_map
from a2router.models import LAYOUTS, BackendError, Route, VirtualDevice


class AudioBackend:
    name = "abstract"

    def __init__(self):
        self.devices = {}
        self.routes = {}
        self.virtual_devices = {}
        self.last_error = ""
        self.endpoint_aliases = {}

    def capabilities(self):
        return {
            "routing": True,
            "virtual_devices": True,
            "layouts": list(LAYOUTS),
            "channel_routing": False,
            "adjustable_latency": False,
            "synchronization": "Audio server manages buffering and clock adaptation; acoustic alignment unverified",
        }

    def list_devices(self):
        return list(self.devices.values())

    def get_device(self, device_id):
        if device_id not in self.devices:
            raise BackendError(f"Device unavailable: {device_id}")
        return self.devices[device_id]

    def list_routes(self):
        return list(self.routes.values())

    def get_route_status(self, route_id):
        if route_id not in self.routes:
            raise BackendError(f"Unknown route: {route_id}")
        return self.routes[route_id]

    def diagnostics(self):
        return {
            "backend": self.name,
            "available": not bool(self.last_error),
            "error": self.last_error,
            "capabilities": self.capabilities(),
            "devices": len(self.devices),
            "routes": [asdict(r) for r in self.list_routes()],
        }

    def _validate_route(self, route, allow_missing=False):
        if type(route.delay_ms) is not int or not 0 <= route.delay_ms <= 10000:
            raise BackendError("Delay must be an integer between 0 and 10000 ms")
        if route.delay_ms and not self.capabilities().get("route_delay", False):
            raise BackendError("This backend does not support additional route delay")
        validate_channel_map(route.channel_map)
        if route.channel_map and not self.capabilities().get("channel_routing"):
            raise BackendError("Channel routing is unavailable in this backend")
        if any(
            r.source_id == route.source_id and r.destination_id == route.destination_id and r.id != route.id
            for r in self.routes.values()
        ):
            raise BackendError("Duplicate route")
        source = self.devices.get(route.source_id)
        dest = self.devices.get(route.destination_id)
        if not source or not dest:
            if allow_missing:
                return
            raise BackendError("Source or destination is unavailable")
        if source.kind != "input" or dest.kind != "output":
            raise BackendError("Select an input or output monitor as source and an output as destination")
        if source.monitor_of == dest.id or (
            source.properties.get("feedback_group")
            and source.properties["feedback_group"] == dest.properties.get("feedback_group")
        ):
            raise BackendError("Feedback: a sink monitor cannot feed its own sink")
        if not source.monitor_of and dest.virtual is not True and not route.monitoring_confirmed:
            raise BackendError("Microphone/input monitoring requires explicit feedback-risk confirmation")
        if route.channel_map:
            if not source.channels or not dest.channels:
                raise BackendError("Channel counts are unavailable")
            validate_channel_map(route.channel_map, source.channels, dest.channels)
        else:
            self._validate_layout(source, dest)

        # Collapse monitor sources onto their parent sinks and reject cycles,
        # including disabled desired routes which could be enabled later.
        def node(ident):
            device = self.devices.get(ident)
            return device.properties.get("feedback_group", ident) if device else ident

        graph = {}
        for r in [*self.routes.values(), route]:
            s = self.devices.get(r.source_id)
            if s and s.monitor_of:
                graph.setdefault(node(s.monitor_of), set()).add(node(r.destination_id))
        start = node(source.monitor_of)
        stack, seen = [node(dest.id)], set()
        while stack:
            node = stack.pop()
            if node == start:
                raise BackendError("Feedback cycle detected")
            if node not in seen:
                seen.add(node)
                stack.extend(graph.get(node, ()))

    def _validate_layout(self, source, dest):
        if not source.positions or source.positions != dest.positions:
            raise BackendError("Channel layouts differ or are unknown; automatic downmix/remix is disabled")

    def create_route(
        self,
        source_id,
        destination_id,
        *,
        monitoring_confirmed=False,
        route_id=None,
        enabled=True,
        allow_missing=False,
        delay_ms=0,
        channel_map=None,
    ):
        if not self.capabilities()["routing"]:
            raise BackendError("Routing is unavailable in this backend")
        route = Route(source_id, destination_id, monitoring_confirmed=monitoring_confirmed, enabled=enabled)
        route.delay_ms = delay_ms
        route.channel_map = deepcopy(channel_map) if channel_map is not None else []
        if route_id:
            route.id = route_id
        if route.id in self.routes:
            old = self.routes[route.id]
            if (old.source_id, old.destination_id) != (source_id, destination_id):
                raise BackendError("Route identifier already belongs to different endpoints")
            return old
        self._validate_route(route, allow_missing)
        self.routes[route.id] = route
        self._reconcile_route(route)
        return route

    def _reconcile_route(self, route):
        if not route.enabled:
            route.status = "disabled"
            route.error = ""
            return
        try:
            self._validate_route(route)
            self._connect(route)
            route.status, route.error = "connected", ""
        except BackendError as exc:
            route.error = str(exc)
            # A format/safety change must stop the previous live connection,
            # not merely replace its visible status with an error.
            try:
                self._disconnect(route)
            except BackendError as cleanup:
                route.error += f"; stopping resource failed: {cleanup}"
            route.status = (
                "pending"
                if (route.source_id not in self.devices or route.destination_id not in self.devices)
                else "error"
            )

    def enable_route(self, route_id):
        route = self.get_route_status(route_id)
        route.enabled = True
        self._reconcile_route(route)

    def disable_route(self, route_id):
        route = self.get_route_status(route_id)
        self._disconnect(route)
        route.enabled, route.status, route.error = False, "disabled", ""

    def remove_route(self, route_id):
        route = self.routes.get(route_id)
        if route:
            self._disconnect(route)
            del self.routes[route_id]

    def create_virtual_device(self, config):
        if not self.capabilities()["virtual_devices"]:
            raise BackendError("Virtual endpoints require a real virtual audio driver on this platform")
        if isinstance(config, dict):
            config = VirtualDevice(**config)
        if config.layout not in self.capabilities()["layouts"]:
            raise BackendError("Unsupported channel layout")
        if not config.name.strip() or len(config.name) > 128 or any(ord(c) < 32 for c in config.name):
            raise BackendError("Device name must contain 1–128 printable characters")
        old = self.virtual_devices.get(config.id)
        if old and old != config:
            raise BackendError("Virtual device ID already has a different definition")
        self._create_virtual(config)
        self.virtual_devices[config.id] = config
        return config

    def remove_virtual_device(self, device_id):
        config = next((v for v in self.virtual_devices.values() if device_id in (v.id, v.device_id)), None)
        if config:
            dependent = [
                r
                for r in self.routes.values()
                if r.source_id == "source:" + config.device_id.removeprefix("sink:") + ".monitor"
                or r.destination_id == config.device_id
            ]
            if dependent:
                raise BackendError("Remove routes using this virtual device first")
            self._remove_virtual(config)
            del self.virtual_devices[config.id]

    def refresh(self, reconcile=True):
        raise NotImplementedError

    def _connect(self, route):
        raise NotImplementedError

    def _disconnect(self, route):
        raise NotImplementedError

    def _create_virtual(self, config):
        raise NotImplementedError

    def _remove_virtual(self, config):
        raise NotImplementedError

    def close(self):
        """Release controller resources, leaving server-owned routes running."""
