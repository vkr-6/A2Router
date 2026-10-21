"""Control-only ctypes integration; PCM and per-source mixing remain native."""

import ctypes
import json
import os
import sys
from pathlib import Path

from a2router.backends.base import AudioBackend
from a2router.backends.windows_virtual import WindowsVirtualDevices
from a2router.models import BackendError, Device


def library_path():
    if "A2ROUTER_WASAPI_DLL" in os.environ:
        return Path(os.environ["A2ROUTER_WASAPI_DLL"])
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "a2router_wasapi.dll"
    return Path(__file__).resolve().parents[2] / "build" / "a2router_wasapi.dll"


class WindowsBackend(AudioBackend):
    name = "Windows WASAPI"

    def __init__(self, bridge=None):
        super().__init__()
        self.bridge = bridge
        self.active_sessions = {}
        self.source_endpoints = {}
        self.telemetry = {}
        self.active_delays = {}
        self.virtual_manager = WindowsVirtualDevices()
        self.has_delay_api = bridge is not None and hasattr(bridge, "ar_source_start_delays")
        self.has_virtual_api = bridge is not None and hasattr(bridge, "ar_virtual_discovery_version")
        if bridge is None:
            path = library_path()
            try:
                self.bridge = ctypes.CDLL(str(path))
                for name in ("ar_devices", "ar_stats", "ar_error"):
                    getattr(self.bridge, name).restype = ctypes.c_char_p
                    getattr(self.bridge, name).argtypes = []
                self.bridge.ar_api_version.argtypes = []
                self.bridge.ar_api_version.restype = ctypes.c_int
                if self.bridge.ar_api_version() != 2:
                    raise BackendError("WASAPI bridge API mismatch; rebuild the native DLL")
                self.bridge.ar_source_start.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_wchar_p]
                self.bridge.ar_source_start.restype = ctypes.c_int
                self.has_virtual_api = hasattr(self.bridge, "ar_virtual_discovery_version")
                if self.has_virtual_api:
                    self.bridge.ar_virtual_discovery_version.argtypes = []
                    self.bridge.ar_virtual_discovery_version.restype = ctypes.c_int
                    self.has_virtual_api = self.bridge.ar_virtual_discovery_version() == 1
                self.has_delay_api = hasattr(self.bridge, "ar_source_start_delays")
                if self.has_delay_api:
                    self.bridge.ar_source_start_delays.argtypes = [
                        ctypes.c_wchar_p,
                        ctypes.c_int,
                        ctypes.c_wchar_p,
                        ctypes.c_wchar_p,
                    ]
                    self.bridge.ar_source_start_delays.restype = ctypes.c_int
                self.bridge.ar_close.argtypes = []
                self.bridge.ar_close.restype = None
            except (OSError, AttributeError, BackendError) as exc:
                self.bridge = None
                self.last_error = f"Build/install a2router_wasapi.dll API v2 first: {exc}"

    def capabilities(self):
        return {
            "routing": self.bridge is not None,
            "virtual_devices": self.bridge is not None
            and self.has_virtual_api
            and self.virtual_manager.available(),
            "layouts": ["stereo"]
            if self.bridge is not None and self.has_virtual_api and self.virtual_manager.available()
            else [],
            "route_delay": self.bridge is not None and self.has_delay_api,
            "channel_routing": False,
            "adjustable_latency": False,
            "synchronization": "Existing per-output WASAPI drift controllers; acoustic alignment unverified",
            "sources": "Active microphone/input endpoints and loopbacks of every active output",
            "mixing": "Independent shared-mode source sessions mixed by Windows; PCM conversion may occur",
            "route_changes": "Changing destinations restarts only the affected source's outputs",
            "virtual_driver": "Render-only WDK driver; signed package/UAC required, implementation UNTESTED",
        }

    def _error(self):
        return (self.bridge.ar_error() or b"WASAPI bridge failure").decode("utf-8", errors="replace")

    def _read_stats(self):
        data = self.bridge.ar_stats()
        if data is None:
            raise BackendError(self._error())
        self.telemetry = json.loads(data)

    def _validate_layout(self, source, dest):
        if source.positions in (("mono",), ("front-center",)) and dest.positions == (
            "front-left",
            "front-right",
        ):
            # WASAPI shared-mode conversion duplicates a mono source into stereo;
            # no source channels are discarded. Surround downmix stays forbidden.
            return
        super()._validate_layout(source, dest)

    def _native_source(self, source_id):
        source = self.devices.get(source_id)
        if source:
            endpoint = self.devices.get(source.monitor_of) if source.monitor_of else source
            if endpoint is None:
                raise BackendError("The monitor's render endpoint is unavailable")
            return (endpoint.properties.get("native_endpoint_id", endpoint.id), not bool(source.monitor_of))
        return self.source_endpoints[source_id]

    def _session_stats(self, source_id):
        native_id, capture_input = self._native_source(source_id)
        return next(
            (
                session
                for session in self.telemetry.get("sessions", [])
                if session["source_id"] == native_id and session["capture_from_input"] == capture_input
            ),
            {},
        )

    def _healthy(self, source_id, destinations):
        stats = self._session_stats(source_id)
        actual = {d["id"] for d in stats.get("devices", []) if d.get("running") and not d.get("faulted")}
        return bool(stats.get("running")) and set(destinations) == actual

    def refresh(self, reconcile=True):
        if self.bridge is None:
            return
        try:
            data = self.bridge.ar_devices()
            if data is None:
                raise BackendError(self._error())
            devices = {}
            for row in json.loads(data):
                ident, name = row.pop("id"), row.pop("name")
                json_id = ident
                kind = row.pop("kind")
                positions = tuple(row.pop("positions", ()))
                properties = row.get("properties", {})
                owned = properties.get("a2router_instance", "").lower()
                if owned and kind == "output" and len(owned) == 32:
                    ident = "sink:a2router_v_" + owned
                    properties["native_endpoint_id"] = json_id
                    row["properties"] = properties
                devices[ident] = Device(ident, name, kind, positions=positions, state="ACTIVE", **row)
                if kind == "output":
                    monitor_id = (
                        "source:" + ident.removeprefix("sink:") + ".monitor"
                        if ident.startswith("sink:a2router_v_")
                        else "wasapi-loopback:" + ident
                    )
                    devices[monitor_id] = Device(
                        monitor_id,
                        name + " (WASAPI loopback)",
                        "input",
                        True,
                        channels=devices[ident].channels,
                        positions=positions,
                        sample_rate=devices[ident].sample_rate,
                        sample_format=devices[ident].sample_format,
                        state="ACTIVE",
                        monitor_of=ident,
                    )
            self.devices, self.last_error = devices, ""
            self._read_stats()
            if reconcile:
                self._apply()
            else:
                for route in self.routes.values():
                    route.resource_ids = []
                    if not route.enabled:
                        route.status, route.error = "disabled", ""
                    elif route.source_id not in self.devices or route.destination_id not in self.devices:
                        route.status, route.error = "pending", "Endpoint unavailable"
                    elif self._healthy(
                        route.source_id,
                        (
                            self.devices[route.destination_id].properties.get(
                                "native_endpoint_id", route.destination_id
                            ),
                        ),
                    ):
                        route.status, route.error = "connected", ""
                        route.resource_ids = [f"wasapi:{route.source_id}->{route.destination_id}"]
                    else:
                        # A session can contain more than one output.
                        stats = self._session_stats(route.source_id)
                        healthy = stats.get("running") and any(
                            d["id"]
                            == self.devices[route.destination_id].properties.get(
                                "native_endpoint_id", route.destination_id
                            )
                            and d.get("running")
                            and not d.get("faulted")
                            for d in stats.get("devices", [])
                        )
                        route.status, route.error = (
                            ("connected", "") if healthy else ("pending", "No active native route")
                        )
        except (BackendError, ValueError, OSError, KeyError, TypeError) as exc:
            self.last_error = str(exc)
            self.devices = {}
            for route in self.routes.values():
                route.status, route.error = "error", str(exc)

    def _apply(self):
        groups = {}
        for route in self.routes.values():
            route.resource_ids = []
            if not route.enabled:
                route.status, route.error = "disabled", ""
                continue
            try:
                self._validate_route(route)
                groups.setdefault(route.source_id, []).append(route)
            except BackendError as exc:
                route.status = (
                    "pending"
                    if route.source_id not in self.devices or route.destination_id not in self.devices
                    else "error"
                )
                route.error = str(exc)
        failures = {}
        for source_id in set(self.active_sessions) - set(groups):
            native_id, capture_input = self.source_endpoints[source_id]
            if not self.bridge.ar_source_start(native_id, int(capture_input), ""):
                failures[source_id] = self._error()
            else:
                self.active_sessions.pop(source_id, None)
                self.source_endpoints.pop(source_id, None)
                self.active_delays.pop(source_id, None)
        for source_id, routes in groups.items():
            ordered = sorted(routes, key=lambda r: r.destination_id)
            target = tuple(
                self.devices[r.destination_id].properties.get("native_endpoint_id", r.destination_id)
                for r in ordered
            )
            delays = tuple(r.delay_ms for r in ordered)
            native_id, capture_input = self._native_source(source_id)
            self.source_endpoints[source_id] = (native_id, capture_input)
            if (
                target != self.active_sessions.get(source_id)
                or delays != self.active_delays.get(source_id)
                or not self._healthy(source_id, target)
            ):
                if self.has_delay_api:
                    started = self.bridge.ar_source_start_delays(
                        native_id, int(capture_input), "\n".join(target), "\n".join(map(str, delays))
                    )
                else:
                    started = self.bridge.ar_source_start(native_id, int(capture_input), "\n".join(target))
                if not started:
                    self.active_sessions.pop(source_id, None)
                    failures[source_id] = self._error()
                else:
                    self.active_sessions[source_id] = target
                    self.active_delays[source_id] = delays
                self._read_stats()
            healthy = source_id not in failures and self._healthy(source_id, target)
            for route in routes:
                route.status = "connected" if healthy else "error"
                route.error = (
                    ""
                    if healthy
                    else failures.get(source_id, "Native session did not report healthy outputs")
                )
                route.resource_ids = [f"wasapi:{source_id}->{route.destination_id}"] if healthy else []
        return failures

    def _connect(self, route):
        self._apply()
        if route.status != "connected":
            raise BackendError(route.error or "WASAPI connection failed")

    def _disconnect(self, route):
        old = route.enabled
        route.enabled = False
        try:
            failures = self._apply()
            if route.source_id in failures:
                raise BackendError(failures[route.source_id])
            route.resource_ids = []
        finally:
            route.enabled = old

    def _create_virtual(self, config):
        if config.device_id in self.devices:
            return  # Existing root instance was verified by native ancestry discovery.
        self.virtual_manager.create(config)
        self.refresh(reconcile=False)
        if config.device_id not in self.devices and not self.virtual_manager.reboot_required:
            raise BackendError(
                "Driver installed but its audio endpoint is not active; inspect Device Manager"
            )

    def _remove_virtual(self, config):
        self.virtual_manager.remove(config)
        self.refresh(reconcile=False)

    def remove_virtual_device(self, device_id):
        config = next((v for v in self.virtual_devices.values() if device_id in (v.id, v.device_id)), None)
        if config and any(
            r.source_id == "source:" + config.device_id.removeprefix("sink:") + ".monitor"
            or r.destination_id == config.device_id
            for r in self.routes.values()
        ):
            raise BackendError("Remove routes using this virtual device first")
        super().remove_virtual_device(device_id)

    def set_route_delay(self, route_id, delay_ms):
        if not self.capabilities().get("route_delay"):
            raise BackendError("Rebuild the WASAPI DLL to enable synchronization delay controls")
        if type(delay_ms) is not int or not 0 <= delay_ms <= 10000:
            raise BackendError("Additional delay must be between 0 and 10000 ms")
        route = self.get_route_status(route_id)
        old_delay = route.delay_ms
        route.delay_ms = delay_ms
        if not route.enabled:
            return
        try:
            self._validate_route(route)
            self._connect(route)
        except BackendError:
            route.delay_ms = old_delay
            self._apply()  # Restore the previous desired setting after a failed restart.
            raise

    def diagnostics(self):
        return {
            **super().diagnostics(),
            "telemetry": self.telemetry,
            "native_library": str(library_path()),
            "processing": "Uncompressed shared-mode PCM; Windows mixing, rate conversion, and mono-to-stereo duplication may occur. Bit-perfect transport unverified.",
            "virtual_driver": self.virtual_manager.diagnostics(),
        }

    def close(self):
        if self.bridge:
            self.bridge.ar_close()
        self.active_sessions.clear()
        self.active_delays.clear()
        self.source_endpoints.clear()
