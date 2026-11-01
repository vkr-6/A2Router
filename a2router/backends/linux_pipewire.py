"""Real PipeWire-Pulse routing, also usable with PulseAudio compatibility servers.

Only pactl is needed. Every module carries an installation owner and definition
UUID. Numeric module IDs are always re-resolved and never trusted across refresh.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from uuid import UUID

from a2router.backends.base import AudioBackend
from a2router.models import LAYOUTS, BackendError, Device


def system_audio_environment():
    """Use host audio utilities with host libraries, including in a frozen bundle."""
    environment = {**os.environ, "LC_ALL": "C"}
    if "LD_LIBRARY_PATH_ORIG" in environment:
        environment["LD_LIBRARY_PATH"] = environment["LD_LIBRARY_PATH_ORIG"]
    elif getattr(__import__("sys"), "frozen", False):
        environment.pop("LD_LIBRARY_PATH", None)
    return environment


class PipeWireBackend(AudioBackend):
    name = "PipeWire-Pulse (pactl)"

    def __init__(self, runner=None, owner=None, graph_runner=None):
        super().__init__()
        self.runner = runner or self._run
        identity = f"{Path.home()}:{getattr(os, 'getuid', lambda: os.environ.get('USERNAME', 'user'))()}"
        self.owner = owner or hashlib.sha256(identity.encode()).hexdigest()[:24]
        self.modules = []
        self.server = {}
        self.stale_resources = []
        self.sink_inputs = []
        self.source_outputs = []
        self.raw_sinks = []
        from a2router.backends.pulse_matrix import PulseMatrix

        self.pulse_matrix = PulseMatrix(self)
        from a2router.backends.pipewire_graph import PipeWireGraph

        if graph_runner is None and runner is None and all(shutil.which(t) for t in ("pw-dump", "pw-link")):
            graph_runner = self._graph_run
        self.graph = PipeWireGraph(graph_runner, self.owner) if graph_runner else None
        self.graph_available = False
        self.graph_error = ""

    def capabilities(self):
        match = re.search(r"PipeWire (\d+)\.(\d+)\.(\d+)", self.server.get("server_name", ""))
        delay = bool(match and tuple(map(int, match.groups())) >= (1, 0, 0))
        return {
            **super().capabilities(),
            "device_controls": True,
            "meters": False,
            "applications": self.graph_available,
            "channel_routing": self.graph_available or self._pulse_mapping(),
            "channel_gain": False,
            "live_channel_routing": self.graph_available,
            "graph_route_delay": False,
            "route_delay": delay,
            "live_route_delay": False,
            "latency_control": "PipeWire latency target; changing an active route requires its restart",
            "channel_routing_reason": (
                "PulseAudio: unity channel remapping/duplication; applying restarts this route"
                if self._pulse_mapping()
                else "PipeWire: unity channel links"
                if self.graph_available
                else self.graph_error or "Channel routing needs pw-dump/pw-link in the same PipeWire session"
            ),
        }

    def _pulse_mapping(self):
        name = self.server.get("server_name", "").lower()
        return bool(name and "pulse" in name and "pipewire" not in name)

    @staticmethod
    def _graph_run(args):
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=8, env=system_audio_environment(), check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError(f"PipeWire graph tools unavailable: {exc}") from exc
        if result.returncode:
            raise BackendError(result.stderr.strip() or "PipeWire graph operation failed")
        return result.stdout

    def _validate_route(self, route, allow_missing=False):
        super()._validate_route(route, allow_missing)
        if route.delay_ms and (route.channel_map or route.source_id.startswith("pw-application:")):
            raise BackendError(
                "Native application/channel links do not support extra delay; reset delay to zero first"
            )
        if any(c["gain"] != 1 for c in route.channel_map):
            raise BackendError("Native audio-server channel routing supports unity gain only")
        if route.channel_map and self._pulse_mapping():
            self.pulse_matrix.plan(route)

    @staticmethod
    def _run(args):
        try:
            completed = subprocess.run(
                ["pactl", *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
                env=system_audio_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError(f"pactl unavailable: {exc}") from exc
        if completed.returncode:
            raise BackendError(completed.stderr.strip() or "pactl command failed")
        return completed.stdout.strip()

    def _json(self, *args):
        try:
            return json.loads(self.runner(["-f", "json", *args]))
        except (ValueError, TypeError) as exc:
            raise BackendError("pactl returned invalid JSON; install a JSON-capable pactl") from exc

    def _modules(self):
        # Some pactl JSON versions omit module indices entirely. The short
        # table is the supported source of module handles on those versions.
        modules = self._json("list", "modules")
        if all("index" in m for m in modules):
            return modules
        rows = self.runner(["list", "short", "modules"]).splitlines()
        indexed = []
        for line in rows:
            columns = line.split("\t")
            if len(columns) >= 3 and columns[0].isdecimal():
                indexed.append({"index": int(columns[0]), "name": columns[1], "argument": columns[2]})
        if any(m["name"] in ("module-null-sink", "module-loopback") for m in modules) and not indexed:
            raise BackendError("Cannot resolve audio server module IDs")
        return indexed

    def _scan(self):
        info = self._json("info")
        if not isinstance(info, dict):
            raise BackendError("Invalid audio server information")
        sinks, sources = self._json("list", "sinks"), self._json("list", "sources")
        self.raw_sinks = sinks
        hidden_monitors = {
            str(s.get("monitor_source"))
            for s in sinks
            if s.get("properties", {}).get("a2router.internal") == "matrix"
        }
        devices = {}
        for kind, rows in (("output", sinks), ("input", sources)):
            for row in rows:
                if row.get("properties", {}).get("a2router.internal") == "matrix" or (
                    kind == "input"
                    and (str(row.get("index")) in hidden_monitors or row.get("name") in hidden_monitors)
                ):
                    continue
                name = row["name"]
                props = row.get("properties", {})
                spec = row.get("sample_specification", "")
                match = re.fullmatch(r"(\S+)\s+(\d+)ch\s+(\d+)Hz", spec)
                positions = tuple(filter(None, row.get("channel_map", "").split(",")))
                virtual = None
                if (
                    props.get("device.class") in ("monitor", "filter", "abstract")
                    or props.get("node.virtual") in (True, "true")
                    or props.get("a2router.owner")
                    or row.get("driver") == "module-null-sink.c"
                ):
                    virtual = True
                elif props.get("device.bus") or props.get("device.api") in ("alsa", "bluez5"):
                    virtual = False
                prefix = "sink:" if kind == "output" else "source:"
                monitor = row.get("monitor_of_sink_name")
                if not monitor and kind == "input":
                    monitor = next((s["name"] for s in sinks if s.get("monitor_source") == name), None)
                # PipeWire pactl versions may report numeric monitor_source.
                if not monitor and kind == "input":
                    monitor = next(
                        (s["name"] for s in sinks if s.get("monitor_source") == row.get("index")), None
                    )
                default_key = "default_sink_name" if kind == "output" else "default_source_name"
                devices[prefix + name] = Device(
                    prefix + name,
                    row.get("description", name),
                    kind,
                    virtual,
                    default=info.get(default_key) == name,
                    channels=int(match[2]) if match else None,
                    positions=positions,
                    sample_rate=int(match[3]) if match else None,
                    sample_format=match[1] if match else None,
                    state=row.get("state", "unknown"),
                    monitor_of="sink:" + monitor if monitor else None,
                    latency=row.get("latency", {}),
                    properties={
                        **props,
                        "server_index": row["index"],
                        "ports": row.get("ports", []),
                        "active_port": row.get("active_port"),
                        "reported_formats": row.get("formats", []),
                        "controls": {
                            "volume_available": bool(row.get("volume")),
                            "volume": min(
                                1.0,
                                max(
                                    (v.get("value", 0) / 65536 for v in row.get("volume", {}).values()),
                                    default=0,
                                ),
                            ),
                            "muted": row.get("mute", False),
                            "peak_available": False,
                        },
                    },
                )
        modules = self._modules()
        sink_inputs = self._json("list", "sink-inputs")
        source_outputs = self._json("list", "source-outputs")
        self.server, self.devices, self.modules = info, devices, modules
        self.sink_inputs, self.source_outputs = sink_inputs, source_outputs
        self.graph_available = False
        if self.graph and "pipewire" in info.get("server_name", "").lower():
            try:
                self.graph.refresh()
                self.graph.verify_server(info)
                self.devices.update(self.graph.applications())
                self.graph_available, self.graph_error = True, ""
            except BackendError as exc:
                self.graph_error = str(exc)
        server_name = info.get("server_name", "unknown")
        self.name = f"{'PipeWire-Pulse' if 'pipewire' in server_name.lower() else 'PulseAudio compatibility'}: {server_name}"

    def _arguments(self, module):
        if self._pulse_mapping():
            # Pulse preserves the raw quoted property list; unlike POSIX shell
            # quoting, its single quotes allow backslash-escaped apostrophes.
            pattern = re.compile(r"""\s*([^\s=]+)=("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s]*)""")
            argument, tokens = module.get("argument", ""), []
            while argument.strip():
                match = pattern.match(argument)
                if not match:
                    return []
                key, value = match.groups()
                if value.startswith(("'", '"')):
                    value = value[1:-1]
                tokens.append(key + "=" + value)
                argument = argument[match.end() :]
            return tokens
        try:
            return shlex.split(module.get("argument", ""))
        except ValueError:
            return []

    def _owned(self, module, kind=None, ident=None):
        if module.get("name") not in (
            "module-null-sink",
            "module-loopback",
            "module-remap-source",
            "module-remap-sink",
        ):
            return False
        tokens = self._arguments(module)
        properties = []
        for token in tokens:
            key, _, value = token.partition("=")
            if key in (
                "sink_properties",
                "source_properties",
                "sink_input_properties",
                "source_output_properties",
            ):
                try:
                    properties.extend(shlex.split(value))
                except ValueError:
                    return False
        if f"a2router.owner={self.owner}" not in properties:
            return False
        return not (kind and f"a2router.{kind}={ident}" not in properties)

    def _find(self, kind, ident):
        return [m for m in self.modules if self._owned(m, kind, ident)]

    @staticmethod
    def _same_module(first, second):
        # Usage counters can change while dependants are being removed.
        return all(first.get(k) == second.get(k) for k in ("index", "name", "argument"))

    def _unload(self, kind, ident):
        # Fresh scan prevents deletion after server restart reuses an index.
        self.modules = self._modules()
        # Dependants are created after their master remap nodes. Recheck every
        # handle because unloading a master may auto-remove dependent modules.
        for module in reversed(self._find(kind, ident)):
            if any(self._same_module(module, current) for current in self._modules()):
                self.runner(["unload-module", str(module["index"])])
        self.modules = self._modules()

    def _load(self, module_name, args, kind, ident, verify):
        # A known definition is an idempotent operation, never a second module.
        self.modules = self._modules()
        existing = self._find(kind, ident)
        if existing:
            if len(existing) != 1 or not verify(existing[0]):
                raise BackendError(
                    "Owned resource exists but failed verification; inspect diagnostics/cleanup"
                )
            return str(existing[0]["index"])
        loaded = False
        result = None
        before_ids = {str(m["index"]) for m in self.modules}
        expected_argument = " ".join(args)
        try:
            result = self.runner(["load-module", module_name, *args])
            loaded = True
            if not result.isdecimal():
                raise BackendError("Audio server returned an invalid module ID")
            for _ in range(15):
                self._scan()
                module = next((m for m in self._find(kind, ident) if str(m["index"]) == result), None)
                if module and verify(module):
                    return result
                time.sleep(0.03)
            raise BackendError("Module loaded but endpoint/stream verification failed")
        except BackendError as exc:
            # The load might have succeeded even if the client timed out.
            try:
                self._unload(kind, ident)
                # If a server/parser lost the proplist tags, only an exact
                # argument echo of THIS new request proves creation ownership.
                for candidate in self._modules():
                    if (
                        str(candidate["index"]) not in before_ids
                        and candidate.get("name") == module_name
                        and candidate.get("argument") == expected_argument
                    ):
                        current = self._modules()
                        if any(self._same_module(candidate, m) for m in current):
                            self.runner(["unload-module", str(candidate["index"])])
                remaining = self._modules()
                if (
                    loaded
                    and result
                    and any(str(m["index"]) == result and m.get("name") == module_name for m in remaining)
                ):
                    raise BackendError("Could not verify removal of newly loaded module " + result)
            except BackendError as cleanup:
                raise BackendError(f"{exc}; cleanup failed: {cleanup}") from exc
            raise BackendError(f"{exc} (creation {'rolled back' if loaded else 'failed'})") from exc

    def _virtual_ok(self, config, module):
        device = self.devices.get(config.device_id)
        return (
            module.get("name") == "module-null-sink"
            and device is not None
            and device.positions == LAYOUTS[config.layout]
            and device.properties.get("a2router.owner") == self.owner
        )

    def _property_argument(self, value):
        if self._pulse_mapping():
            # pa_modargs_get_proplist parses the raw value (one escaping level).
            return "'" + value.replace("'", "\\'") + "'"
        # Pulse module arguments have their own quote parser. POSIX shlex.quote
        # uses quote concatenation for apostrophes, which that parser does not
        # support. Nest escaped double quotes explicitly instead.
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _legacy_property_parser(self):
        match = re.search(r"PipeWire (\d+)\.(\d+)\.(\d+)", self.server.get("server_name", ""))
        return bool(match and tuple(map(int, match.groups())) <= (0, 3, 48))

    @staticmethod
    def _legacy_description(name):
        # 0.3.48 skips escaped characters but keeps the backslashes verbatim.
        # Use one quoting level, with a delimiter absent from the actual name.
        if "\\" not in name:
            for delimiter in ('"', "'"):
                if delimiter not in name:
                    return delimiter + name + delimiter
        raise BackendError(
            "PipeWire 0.3.48 cannot preserve names containing both quote types or backslashes; "
            "use a simpler name or upgrade PipeWire"
        )

    def _create_virtual(self, config):
        UUID(config.id)
        sink_name = config.device_id.removeprefix("sink:")
        # libpulse proplist quoting is separate from shell quoting; no shell is used.
        quoted = '"' + config.name.replace("\\", "\\\\").replace('"', '\\"') + '"'
        properties = f"device.description={quoted} a2router.owner={self.owner} a2router.virtual={config.id}"
        description_args = []
        if self._legacy_property_parser():
            # Older PipeWire preserves arbitrary top-level properties, so avoid
            # its broken second parse of a nested quoted description.
            description_args = ["device.description=" + self._legacy_description(config.name)]
            properties = f"a2router.owner={self.owner} a2router.virtual={config.id}"
        if config.device_id in self.devices and not self._find("virtual", config.id):
            raise BackendError("Sink name is already in use by an unowned resource")
        self._load(
            "module-null-sink",
            [
                f"sink_name={sink_name}",
                f"channels={len(LAYOUTS[config.layout])}",
                "channel_map=" + ",".join(LAYOUTS[config.layout]),
                "sink_properties=" + self._property_argument(properties),
                *description_args,
            ],
            "virtual",
            config.id,
            lambda module: self._virtual_ok(config, module),
        )
        self._scan()

    def _remove_virtual(self, config):
        self._unload("virtual", config.id)
        self._scan()

    def _route_ok(self, route, module):
        source, dest = self.devices.get(route.source_id), self.devices.get(route.destination_id)
        if not source or not dest or module.get("name") != "module-loopback":
            return False
        index = str(module["index"])
        sink_ok = any(
            str(s.get("owner_module")) == index and str(s.get("sink")) == str(dest.properties["server_index"])
            for s in self.sink_inputs
        )
        source_ok = any(
            str(s.get("owner_module")) == index
            and str(s.get("source")) == str(source.properties["server_index"])
            for s in self.source_outputs
        )
        requested = f"latency_msec={route.delay_ms}"
        latency = [a for a in self._arguments(module) if a.startswith("latency_msec=")]
        delay_ok = latency == ([requested] if route.delay_ms else [])
        return sink_ok and source_ok and delay_ok

    def _connect(self, route):
        UUID(route.id)
        if route.channel_map and self._pulse_mapping():
            self._unload("route", route.id)
            self.pulse_matrix.connect(route)
            return
        self._unload("matrix", route.id)
        if route.channel_map or route.source_id.startswith("pw-application:"):
            if not self.graph_available:
                raise BackendError(
                    "Application/channel routing requires pw-dump and pw-link with a native PipeWire session"
                )
            self._unload("route", route.id)
            self.graph.connect(route, self.devices)
            return
        if self.graph_available:
            self.graph.disconnect(route.id)
        source = self.devices[route.source_id]
        props = f"a2router.owner={self.owner} a2router.route={route.id} media.name=a2router"
        module = self._load(
            "module-loopback",
            [
                "source=" + route.source_id.removeprefix("source:"),
                "sink=" + route.destination_id.removeprefix("sink:"),
                "source_dont_move=true",
                "sink_dont_move=true",
                "remix=false",
                *([f"latency_msec={route.delay_ms}"] if route.delay_ms else []),
                f"channels={source.channels}",
                "channel_map=" + ",".join(source.positions),
                "sink_input_properties=" + self._property_argument(props),
                "source_output_properties=" + self._property_argument(props),
            ],
            "route",
            route.id,
            lambda m: self._route_ok(route, m),
        )
        route.resource_ids = [module]

    def set_route_delay(self, route_id, delay_ms, *, allow_restart=False):
        if not self.capabilities().get("route_delay"):
            raise BackendError("Latency targets require PipeWire 1.0 or newer")
        if type(delay_ms) is not int or not 0 <= delay_ms <= 10000:
            raise BackendError("Delay must be an integer between 0 and 10000 ms")
        route = self.get_route_status(route_id)
        if route.delay_ms == delay_ms:
            return "Latency target unchanged"
        live = route.enabled and self.transport_running and bool(self._find("route", route.id))
        if live and not allow_restart:
            raise BackendError("Changing this latency target requires restarting the selected route")
        from dataclasses import replace

        self._validate_route(replace(route, delay_ms=delay_ms), allow_missing=True)
        previous = route.delay_ms
        self._disconnect(route)
        route.delay_ms = delay_ms
        self._reconcile_route(route)
        if route.status == "error":
            reason = route.error
            route.delay_ms = previous
            self._disconnect(route)
            self._reconcile_route(route)
            raise BackendError(f"Latency target failed: {reason}; recovery status: {route.status}")
        return "Server latency target updated; actual acoustic delay is unmeasured"

    def _disconnect(self, route):
        self._unload("route", route.id)
        self._unload("matrix", route.id)
        if self.graph_available or any(r.startswith("link:") for r in route.resource_ids):
            if not self.graph:
                raise BackendError("Graph cleanup is unavailable; preserve route definitions and retry")
            self.graph.disconnect(route.id)
        route.resource_ids = []

    def refresh(self, reconcile=True):
        try:
            self._scan()
            self.last_error = ""
        except BackendError as exc:
            self.last_error = str(exc)
            self.devices = {}
            for route in self.routes.values():
                route.status, route.error, route.resource_ids = "pending", str(exc), []
            return
        if not reconcile:
            for route in self.routes.values():
                if route.channel_map and self._pulse_mapping():
                    connected = self.pulse_matrix.healthy(route)
                    route.resource_ids = [str(m["index"]) for m in self._find("matrix", route.id)]
                    route.status = "connected" if connected else "pending" if route.enabled else "disabled"
                    route.error = (
                        "" if connected or not route.enabled else "PulseAudio mapping resources unavailable"
                    )
                    continue
                if route.channel_map or route.source_id.startswith("pw-application:"):
                    links = self.graph.owned(route.id) if self.graph_available else []
                    route.resource_ids = [self.graph.resource(link) for link in links]
                    connected = self.graph_available and self.graph.healthy(route, self.devices)
                    route.status = "connected" if connected else "pending" if route.enabled else "disabled"
                    route.error = (
                        "" if connected or not route.enabled else "Application/channel graph unavailable"
                    )
                    continue
                modules = self._find("route", route.id)
                route.resource_ids = [str(m["index"]) for m in modules]
                if modules and all(self._route_ok(route, m) for m in modules):
                    route.status = "connected"
                    route.error = (
                        "" if route.enabled else "Live module exists for disabled definition; Stop to unload"
                    )
                else:
                    route.status = "pending" if route.enabled else "disabled"
                    route.error = "Endpoints or route resources unavailable" if route.enabled else ""
            self._update_stale()
            return
        # Restore managed virtual definitions after server restart.
        for config in self.virtual_devices.values():
            if config.device_id not in self.devices:
                try:
                    self._create_virtual(config)
                except BackendError as exc:
                    self.last_error = str(exc)
        for route in self.routes.values():
            try:
                modules = self._find("route", route.id)
                if (
                    not route.enabled
                    or route.source_id not in self.devices
                    or route.destination_id not in self.devices
                ):
                    self._disconnect(route)
                elif modules and not all(self._route_ok(route, m) for m in modules):
                    self._disconnect(route)  # Never accept an automatically moved stream.
                self._reconcile_route(route)
            except BackendError as exc:
                route.status, route.error = "error", str(exc)
        self._update_stale()

    def _update_stale(self):
        known = {
            str(m["index"])
            for kind, values in (
                ("route", self.routes),
                ("matrix", self.routes),
                ("virtual", self.virtual_devices),
            )
            for ident in values
            for m in self._find(kind, ident)
        }
        self.stale_resources = [
            str(m["index"]) for m in self.modules if self._owned(m) and str(m["index"]) not in known
        ]
        if self.graph_available:
            self.stale_resources.extend(
                self.graph.resource(link)
                for link in self.graph.owned()
                if link.get("info", {}).get("props", {}).get("a2router.route") not in self.routes
            )

    def cleanup_owned(self):
        """Explicitly requested cleanup, including orphaned modules after a crash."""
        self.modules = self._modules()
        if self.graph_available:
            self.graph.disconnect()
        for name in ("module-loopback", "module-remap-sink", "module-remap-source", "module-null-sink"):
            for m in list(self.modules):
                if m["name"] == name and self._owned(m):
                    fresh = self._modules()
                    if any(self._same_module(x, m) for x in fresh):
                        self.runner(["unload-module", str(m["index"])])
        for route in self.routes.values():
            route.enabled, route.status, route.resource_ids = False, "disabled", []
        self.virtual_devices.clear()
        self._scan()

    def diagnostics(self):
        return {
            **super().diagnostics(),
            "server": self.server,
            "application_graph_error": self.graph_error,
            "channel_processing": (
                "PulseAudio remap-sink/loopback at unity; mapping changes restart only this route"
                if self._pulse_mapping()
                else "Native PipeWire unity links; original application output is retained"
            ),
            "owned_channel_links": [self.graph.resource(link) for link in self.graph.owned()]
            if self.graph_available
            else [],
            "stale_owned_modules": self.stale_resources,
            "processing": "Server PCM mixing/rate conversion may occur. Bit-perfect transport is not verified.",
            "monitoring": "GUI subscribes to pactl events with 250 ms debounce; 3 second polling fallback",
            "delay_control": "PipeWire 1.0+ latency target; explicit per-route restart, not verified acoustic alignment",
            "latency": "pactl device latency values are reported in microseconds; end-to-end latency is unknown",
        }

    def set_device_volume(self, device_id, volume):
        if type(volume) not in (int, float) or not 0 <= volume <= 1:
            raise BackendError("Volume must be between 0 and 1")
        device = self.get_device(device_id)
        command = "set-sink-volume" if device.kind == "output" else "set-source-volume"
        self.runner([command, device_id.split(":", 1)[1], str(round(volume * 65536))])
        self._scan()
        observed = self.get_device(device_id).properties.get("controls", {}).get("volume")
        if type(observed) not in (int, float) or abs(observed - volume) > 1 / 65536 + 1e-6:
            raise BackendError("Audio server volume readback did not confirm the change")

    def set_device_mute(self, device_id, muted):
        if type(muted) is not bool:
            raise BackendError("Mute must be a boolean")
        device = self.get_device(device_id)
        command = "set-sink-mute" if device.kind == "output" else "set-source-mute"
        self.runner([command, device_id.split(":", 1)[1], "1" if muted else "0"])
        self._scan()
        if self.get_device(device_id).properties.get("controls", {}).get("muted") is not muted:
            raise BackendError("Audio server mute readback did not confirm the change")
