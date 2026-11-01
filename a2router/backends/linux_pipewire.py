"""Real PipeWire-Pulse routing, also usable with PulseAudio compatibility servers.

Only pactl is needed. Every module carries an installation owner and definition
UUID. Numeric module IDs are always re-resolved and never trusted across refresh.
"""

import hashlib
import json
import os
import re
import shlex
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

    def __init__(self, runner=None, owner=None):
        super().__init__()
        self.runner = runner or self._run
        identity = f"{Path.home()}:{getattr(os, 'getuid', lambda: os.environ.get('USERNAME', 'user'))()}"
        self.owner = owner or hashlib.sha256(identity.encode()).hexdigest()[:24]
        self.modules = []
        self.server = {}
        self.stale_resources = []
        self.sink_inputs = []
        self.source_outputs = []

    def capabilities(self):
        match = re.search(r"PipeWire (\d+)\.(\d+)\.(\d+)", self.server.get("server_name", ""))
        delay = bool(match and tuple(map(int, match.groups())) >= (1, 0, 0))
        return {
            **super().capabilities(),
            "device_controls": True,
            "meters": False,
            "route_delay": delay,
            "live_route_delay": False,
            "latency_control": "PipeWire latency target; changing an active route requires its restart",
        }

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
        devices = {}
        for kind, rows in (("output", sinks), ("input", sources)):
            for row in rows:
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
        server_name = info.get("server_name", "unknown")
        self.name = f"{'PipeWire-Pulse' if 'pipewire' in server_name.lower() else 'PulseAudio compatibility'}: {server_name}"

    @staticmethod
    def _arguments(module):
        try:
            return shlex.split(module.get("argument", ""))
        except ValueError:
            return []

    def _owned(self, module, kind=None, ident=None):
        if module.get("name") not in ("module-null-sink", "module-loopback"):
            return False
        tokens = self._arguments(module)
        properties = []
        for token in tokens:
            key, _, value = token.partition("=")
            if key in ("sink_properties", "sink_input_properties", "source_output_properties"):
                try:
                    properties.extend(shlex.split(value))
                except ValueError:
                    return False
        if f"a2router.owner={self.owner}" not in properties:
            return False
        return not (kind and f"a2router.{kind}={ident}" not in properties)

    def _find(self, kind, ident):
        return [m for m in self.modules if self._owned(m, kind, ident)]

    def _unload(self, kind, ident):
        # Fresh scan prevents deletion after server restart reuses an index.
        self.modules = self._modules()
        for module in self._find(kind, ident):
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
                        if candidate in current:
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

    @staticmethod
    def _property_argument(value):
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
            for kind, values in (("route", self.routes), ("virtual", self.virtual_devices))
            for ident in values
            for m in self._find(kind, ident)
        }
        self.stale_resources = [
            str(m["index"]) for m in self.modules if self._owned(m) and str(m["index"]) not in known
        ]

    def cleanup_owned(self):
        """Explicitly requested cleanup, including orphaned modules after a crash."""
        self.modules = self._modules()
        for name in ("module-loopback", "module-null-sink"):
            for m in list(self.modules):
                if m["name"] == name and self._owned(m):
                    fresh = self._modules()
                    if any(x["index"] == m["index"] and x == m for x in fresh):
                        self.runner(["unload-module", str(m["index"])])
        for route in self.routes.values():
            route.enabled, route.status, route.resource_ids = False, "disabled", []
        self.virtual_devices.clear()
        self._scan()

    def diagnostics(self):
        return {
            **super().diagnostics(),
            "server": self.server,
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
