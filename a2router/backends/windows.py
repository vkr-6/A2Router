"""Control-only ctypes integration; PCM and per-source mixing remain native."""

import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path

from a2router.backends import windows_vbcable
from a2router.backends.base import AudioBackend
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
        self.active_matrices = {}
        self.format_cache = {}
        self._calibration_cancel = threading.Event()
        self.has_matrix_api = bridge is not None and hasattr(bridge, "ar_source_start_matrix")
        self.has_live_delay_api = bridge is not None and hasattr(bridge, "ar_source_set_delay")
        self.has_delay_api = bridge is not None and hasattr(bridge, "ar_source_start_delays")
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
                self.has_delay_api = hasattr(self.bridge, "ar_source_start_delays")
                if self.has_delay_api:
                    self.bridge.ar_source_start_delays.argtypes = [
                        ctypes.c_wchar_p,
                        ctypes.c_int,
                        ctypes.c_wchar_p,
                        ctypes.c_wchar_p,
                    ]
                    self.bridge.ar_source_start_delays.restype = ctypes.c_int
                self.has_live_delay_api = hasattr(self.bridge, "ar_source_set_delay")
                if self.has_live_delay_api:
                    self.bridge.ar_source_set_delay.argtypes = [
                        ctypes.c_wchar_p,
                        ctypes.c_int,
                        ctypes.c_wchar_p,
                        ctypes.c_int64,
                    ]
                    self.bridge.ar_source_set_delay.restype = ctypes.c_int
                self.has_matrix_api = hasattr(self.bridge, "ar_source_start_matrix")
                if self.has_matrix_api:
                    self.bridge.ar_source_start_matrix.argtypes = [
                        ctypes.c_wchar_p,
                        ctypes.c_int,
                        ctypes.c_wchar_p,
                        ctypes.c_wchar_p,
                        ctypes.c_wchar_p,
                    ]
                    self.bridge.ar_source_start_matrix.restype = ctypes.c_int
                signatures = {
                    "ar_controls": ([], ctypes.c_char_p),
                    "ar_set_device_volume": ([ctypes.c_wchar_p, ctypes.c_float], ctypes.c_int),
                    "ar_set_device_mute": ([ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
                    "ar_device_formats": ([ctypes.c_wchar_p], ctypes.c_char_p),
                    "ar_set_device_format": ([ctypes.c_wchar_p] + [ctypes.c_int] * 5, ctypes.c_int),
                    "ar_source_start_config": (
                        [ctypes.c_wchar_p, ctypes.c_int] + [ctypes.c_wchar_p] * 4,
                        ctypes.c_int,
                    ),
                    "ar_source_set_volume": (
                        [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_float],
                        ctypes.c_int,
                    ),
                    "ar_calibration_record": (
                        [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_float, ctypes.c_int],
                        ctypes.c_char_p,
                    ),
                    "ar_calibration_reset": ([], None),
                    "ar_calibration_cancel": ([], None),
                    "ar_calibration_version": ([], ctypes.c_int),
                    "ar_routing_controls_version": ([], ctypes.c_int),
                    "ar_rename_device": ([ctypes.c_wchar_p, ctypes.c_wchar_p], ctypes.c_int),
                }
                for name, (arguments, result) in signatures.items():
                    if hasattr(self.bridge, name):
                        function = getattr(self.bridge, name)
                        function.argtypes, function.restype = arguments, result
                self.bridge.ar_close.argtypes = []
                self.bridge.ar_close.restype = None
            except (OSError, AttributeError, BackendError) as exc:
                self.bridge = None
                self.last_error = f"Build/install a2router_wasapi.dll API v2 first: {exc}"

    def capabilities(self):
        return {
            "routing": self.bridge is not None,
            "virtual_devices": False,
            "layouts": [],
            "virtual_device_provider": "VB-CABLE",
            "install_virtual_driver": self.bridge is not None
            and os.name == "nt"
            and (windows_vbcable.payload_directory() / "VBCABLE_Setup_x64.exe").is_file(),
            "live_route_delay": self.bridge is not None and self.has_live_delay_api,
            "route_delay": self.bridge is not None and self.has_delay_api,
            "channel_routing": self.bridge is not None and self.has_matrix_api,
            "route_controls": self.bridge is not None
            and all(
                hasattr(self.bridge, name)
                for name in ("ar_source_start_config", "ar_source_set_volume", "ar_routing_controls_version")
            )
            and self.bridge.ar_routing_controls_version() == 1,
            "calibration": self.bridge is not None
            and all(
                hasattr(self.bridge, name)
                for name in (
                    "ar_calibration_record",
                    "ar_calibration_reset",
                    "ar_calibration_cancel",
                    "ar_calibration_version",
                )
            )
            and self.bridge.ar_calibration_version() == 1,
            "device_controls": self.bridge is not None and hasattr(self.bridge, "ar_set_device_volume"),
            "meters": self.bridge is not None and hasattr(self.bridge, "ar_controls"),
            "device_configuration": self.bridge is not None and hasattr(self.bridge, "ar_set_device_format"),
            "device_rename": self.bridge is not None and hasattr(self.bridge, "ar_rename_device"),
            "adjustable_latency": False,
            "synchronization": "Existing per-output WASAPI drift controllers; acoustic alignment unverified",
            "sources": "Active microphone/input endpoints and loopbacks of every active output",
            "mixing": "Independent shared-mode source sessions mixed by Windows; PCM conversion may occur",
            "route_changes": "Changing destinations restarts only the affected source's outputs",
            "virtual_driver": "VB-CABLE by VB-Audio; installed on demand from Virtual devices",
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
            if source.properties.get("capture_endpoint_id"):
                return source.properties["capture_endpoint_id"], True
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
        enumerated = False
        try:
            data = self.bridge.ar_devices()
            if data is None:
                raise BackendError(self._error())
            devices = {}
            for row in json.loads(data):
                ident, name = row.pop("id"), row.pop("name")
                kind = row.pop("kind")
                positions = tuple(row.pop("positions", ()))
                properties = row.setdefault("properties", {})
                # Classify actual enumerated endpoints using adapter branding,
                # not a user-editable endpoint name or its position in the list.
                if properties.get("interface_name", "").casefold() in (
                    "vb-audio virtual cable",
                    "vb-audio point",
                ):
                    properties.setdefault("virtual_driver", "VB-CABLE")
                    properties.setdefault("feedback_group", "vbcable:base")
                    row["virtual"] = True
                if properties.get("virtual_driver") == "VB-CABLE":
                    properties["feedback_group"] = "vbcable:base"
                if ident in self.format_cache:
                    properties["supported_formats"] = self.format_cache[ident]
                if properties.get("controls"):
                    properties["controls"]["observed_at"] = time.monotonic()
                devices[ident] = Device(ident, name, kind, positions=positions, state="ACTIVE", **row)
                if kind == "output":
                    monitor_id = "wasapi-loopback:" + ident
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
                        properties=dict(devices[ident].properties),
                    )
            cable_outputs = {}
            for device in devices.values():
                if device.kind == "output" and device.properties.get("virtual_driver") == "VB-CABLE":
                    cable_outputs.setdefault(device.properties["feedback_group"], []).append(device.id)
            for device in devices.values():
                group = device.properties.get("feedback_group")
                if device.kind == "input" and not device.monitor_of and group in cable_outputs:
                    device.monitor_of = cable_outputs[group][0]
                    device.properties["capture_endpoint_id"] = device.id
            self.devices, self.last_error = devices, ""
            self._update_cable_controls()
            enumerated = True
            stats_ok = True
            try:
                self._read_stats()
            except (BackendError, ValueError) as exc:
                stats_ok = False
                self.telemetry = {}
                self.last_error = f"Audio telemetry: {exc}"
            if reconcile and stats_ok:
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
            if not enumerated:
                self.devices = {}
            for route in self.routes.values():
                route.status, route.error = "error", str(exc)

    def _apply(self):
        groups = {}
        for route in self.routes.values():
            route.resource_ids = []
            if not route.enabled or not self.transport_running:
                route.status, route.error = ("disabled" if not route.enabled else "stopped"), ""
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
                self.active_matrices.pop(source_id, None)
        for source_id, routes in groups.items():
            ordered = sorted(routes, key=lambda r: r.destination_id)
            target = tuple(
                self.devices[r.destination_id].properties.get("native_endpoint_id", r.destination_id)
                for r in ordered
            )
            delays = tuple(r.delay_ms for r in ordered)
            matrices = tuple(json.dumps(r.channel_map, sort_keys=True) for r in ordered)
            native_id, capture_input = self._native_source(source_id)
            self.source_endpoints[source_id] = (native_id, capture_input)
            if (
                target != self.active_sessions.get(source_id)
                or delays != self.active_delays.get(source_id)
                or matrices != self.active_matrices.get(source_id)
                or not self._healthy(source_id, target)
            ):
                if self.capabilities().get("route_controls"):
                    rows = []
                    for route in ordered:
                        values = [str(len(route.channel_map))]
                        for connection in route.channel_map:
                            values.extend(str(connection[k]) for k in ("source", "destination", "gain"))
                        rows.append(" ".join(values))
                    started = self.bridge.ar_source_start_config(
                        native_id,
                        int(capture_input),
                        "\n".join(target),
                        "\n".join(map(str, delays)),
                        "\n".join(rows),
                        "\n".join(str(0 if r.muted else r.volume) for r in ordered),
                    )
                elif self.has_matrix_api and any(r.channel_map for r in ordered):
                    rows = []
                    for route in ordered:
                        values = [str(len(route.channel_map))]
                        for connection in route.channel_map:
                            values.extend(str(connection[k]) for k in ("source", "destination", "gain"))
                        rows.append(" ".join(values))
                    started = self.bridge.ar_source_start_matrix(
                        native_id,
                        int(capture_input),
                        "\n".join(target),
                        "\n".join(map(str, delays)),
                        "\n".join(rows),
                    )
                elif self.has_delay_api:
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
                    self.active_matrices[source_id] = matrices
                self._read_stats()
            if source_id not in failures and self.capabilities().get("route_controls"):
                for route, destination in zip(ordered, target):
                    desired = 0 if route.muted else route.volume
                    observed = next(
                        (
                            d.get("volume")
                            for d in self._session_stats(source_id).get("devices", [])
                            if d.get("id") == destination
                        ),
                        None,
                    )
                    if observed is None or abs(observed - desired) > 0.0001:
                        if not self.bridge.ar_source_set_volume(
                            native_id, int(capture_input), destination, desired
                        ):
                            failures[source_id] = self._error()
                            break
                        if not self._wait_stream_gain(source_id, destination, desired):
                            failures[source_id] = "Native stream gain could not be verified"
                            break
                if source_id in failures:
                    if self.bridge.ar_source_start(native_id, int(capture_input), ""):
                        self.active_sessions.pop(source_id, None)
                        self.active_delays.pop(source_id, None)
                        self.active_matrices.pop(source_id, None)
                    else:
                        failures[source_id] += "; stopping unverified playback failed: " + self._error()
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

    def remove_virtual_device(self, device_id):
        raise BackendError(
            "VB-CABLE is a shared driver. Use its vendor installer to uninstall it explicitly."
        )

    def reset_calibration(self):
        self._calibration_cancel.clear()
        self.bridge.ar_calibration_reset()

    def cancel_calibration(self):
        # Explicitly lock-free native cancellation; safe from the Qt thread.
        self._calibration_cancel.set()
        if self.bridge and hasattr(self.bridge, "ar_calibration_cancel"):
            self.bridge.ar_calibration_cancel()

    def calibration_cancelled(self):
        return self._calibration_cancel.is_set()

    def record_calibration(self, microphone_id, output_id, level, channel):
        if not self.capabilities().get("calibration"):
            raise BackendError("Native calibration is unavailable")
        payload = self.bridge.ar_calibration_record(microphone_id, output_id, level, channel)
        if payload is None:
            raise BackendError(self._error())
        try:
            return json.loads(payload)
        except (ValueError, TypeError) as exc:
            raise BackendError("Invalid native recording payload") from exc

    def _wait_stream_gain(self, source_id, destination_id, expected):
        # Telemetry is published periodically by the native supervisor. The
        # control call verifies WASAPI synchronously, but its snapshot can lag.
        deadline = time.monotonic() + 0.6
        while True:
            self._read_stats()
            observed = next(
                (
                    d.get("volume")
                    for d in self._session_stats(source_id).get("devices", [])
                    if d.get("id") == destination_id
                ),
                None,
            )
            if type(observed) in (int, float) and abs(observed - expected) <= 0.0001:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def set_route_volume(self, route_id, volume=None, muted=None):
        if not self.capabilities().get("route_controls"):
            raise BackendError("Native stream controls are unavailable; rebuild the DLL")
        route = self.get_route_status(route_id)
        gain = route.volume if volume is None else volume
        mute = route.muted if muted is None else muted
        if type(gain) not in (int, float) or not 0 <= gain <= 1 or type(mute) is not bool:
            raise BackendError("Invalid stream volume/mute")
        if route.enabled and self.transport_running and route.status == "connected":
            source, capture = self._native_source(route.source_id)
            dest = self.get_device(route.destination_id).properties.get(
                "native_endpoint_id", route.destination_id
            )
            old = 0 if route.muted else route.volume
            if not self.bridge.ar_source_set_volume(source, int(capture), dest, 0 if mute else gain):
                raise BackendError(self._error())
            try:
                if not self._wait_stream_gain(route.source_id, dest, 0 if mute else gain):
                    raise BackendError("Stream gain telemetry did not confirm the change")
            except BackendError as exc:
                rollback = bool(self.bridge.ar_source_set_volume(source, int(capture), dest, old))
                try:
                    rollback = rollback and self._wait_stream_gain(route.source_id, dest, old)
                except BackendError:
                    rollback = False
                raise BackendError(
                    f"{exc}; "
                    + ("previous stream gain restored" if rollback else "stream gain rollback unverified")
                ) from exc
        route.volume, route.muted = gain, mute
        self._update_cable_controls()

    def _cable_routes(self, device):
        group = device.properties.get("feedback_group")
        return [
            r
            for r in self.routes.values()
            if self.devices.get(r.source_id)
            and self.devices[r.source_id].properties.get("feedback_group") == group
        ]

    def _update_cable_controls(self):
        for device in self.devices.values():
            if device.properties.get("virtual_driver") != "VB-CABLE":
                continue
            routes = self._cable_routes(device)
            common = {(r.volume, r.muted) for r in routes}
            control = device.properties.setdefault("controls", {})
            control["volume_available"] = (
                bool(routes) and len(common) == 1 and self.capabilities().get("route_controls", False)
            )
            control["scope"] = "A2Router cable routes only"
            control["reason"] = (
                "Rebuild the DLL for routed cable gain controls"
                if not self.capabilities().get("route_controls")
                else "Add a cable route, or adjust differing gains with Selected route level"
            )
            if len(common) == 1:
                control["volume"], control["muted"] = next(iter(common))

    def _set_cable_controls(self, device, *, volume=None, muted=None):
        routes = self._cable_routes(device)
        if not routes:
            raise BackendError("Add a route from this cable before changing its routed playback")
        previous = [(r.id, r.volume, r.muted) for r in routes]
        changed = []
        try:
            for route in routes:
                self.set_route_volume(route.id, volume, muted)
                changed.append(route.id)
        except BackendError as exc:
            errors = []
            for ident, gain, mute in previous:
                if ident in changed:
                    try:
                        self.set_route_volume(ident, gain, mute)
                    except BackendError as rollback:
                        errors.append(str(rollback))
            raise BackendError(
                f"Cable gain failed: {exc}"
                + ("; rollback errors: " + "; ".join(errors) if errors else "; previous gains restored")
            ) from exc

    def poll_controls(self):
        if not self.bridge or not hasattr(self.bridge, "ar_controls"):
            return
        payload = self.bridge.ar_controls()
        if payload is None:
            for device in self.devices.values():
                controls = device.properties.get("controls", {})
                controls["peak_available"] = False
            raise BackendError(self._error())
        for row in json.loads(payload):
            device = self.devices.get(row["id"])
            if device:
                device.properties["controls"] = {**row["controls"], "observed_at": time.monotonic()}
        self._update_cable_controls()

    def set_device_volume(self, device_id, volume):
        if type(volume) not in (int, float) or not 0 <= volume <= 1:
            raise BackendError("Volume must be between 0 and 1")
        device = self.get_device(device_id)
        if device.properties.get("virtual_driver") == "VB-CABLE":
            return self._set_cable_controls(device, volume=volume)
        if not self.capabilities()["device_controls"] or not self.bridge.ar_set_device_volume(
            device_id, volume
        ):
            raise BackendError(self._error() if self.bridge else "Device controls unavailable")
        self.poll_controls()

    def set_device_mute(self, device_id, muted):
        device = self.get_device(device_id)
        if type(muted) is not bool:
            raise BackendError("Mute must be a boolean")
        if device.properties.get("virtual_driver") == "VB-CABLE":
            return self._set_cable_controls(device, muted=muted)
        if not self.capabilities()["device_controls"] or not self.bridge.ar_set_device_mute(
            device_id, int(muted)
        ):
            raise BackendError(self._error() if self.bridge else "Device controls unavailable")
        self.poll_controls()

    def inspect_formats(self, device_id):
        self.get_device(device_id)
        if not self.capabilities()["device_configuration"]:
            raise BackendError("Rebuild the native bridge to configure formats")
        payload = self.bridge.ar_device_formats(device_id)
        if payload is None:
            raise BackendError(self._error())
        formats = json.loads(payload)
        for item in formats:
            self._validate_format(item)
        self.format_cache[device_id] = formats
        self.devices[device_id].properties["supported_formats"] = formats
        return "" if formats else "No exact formats reported by the driver. Use Windows Sound."

    @staticmethod
    def _validate_format(config):
        if not isinstance(config, dict) or set(config) != {
            "channels",
            "sample_rate",
            "bits",
            "container_bits",
            "encoding",
        }:
            raise BackendError("Invalid device format fields")
        if any(type(config[k]) is not int for k in ("channels", "sample_rate", "bits", "container_bits")):
            raise BackendError("Format values must be integers")
        if config["channels"] not in (1, 2, 4, 6, 8, 16) or not 8000 <= config["sample_rate"] <= 192000:
            raise BackendError("Unsupported channel count or sample rate")
        if (
            config["bits"] not in (16, 24, 32)
            or config["container_bits"] not in (16, 24, 32)
            or config["bits"] > config["container_bits"]
        ):
            raise BackendError("Invalid bit depth")
        if config["encoding"] not in ("pcm", "float") or (
            config["encoding"] == "float" and (config["bits"] != 32 or config["container_bits"] != 32)
        ):
            raise BackendError("Invalid sample encoding")

    def configure_device_format(self, device_id, config):
        self._validate_format(config)
        self.get_device(device_id)
        if not self.capabilities()["device_configuration"]:
            raise BackendError("Native device configuration is unavailable")
        group = self.get_device(device_id).properties.get("feedback_group")
        dependent = False
        for route in self.routes.values():
            if not route.enabled or (
                not self.transport_running
                and not route.resource_ids
                and route.source_id not in self.active_sessions
            ):
                continue
            source = self.devices.get(route.source_id)
            destination = self.devices.get(route.destination_id)
            if (
                route.destination_id == device_id
                or route.source_id == device_id
                or (source and source.monitor_of == device_id)
            ):
                dependent = True
            if group and any(
                device and device.properties.get("feedback_group") == group
                for device in (source, destination)
            ):
                dependent = True
        if dependent:
            raise BackendError("Stop routes using this endpoint before changing its format")
        if config not in self.format_cache.get(device_id, []):
            raise BackendError("Scan formats and select an exact driver-supported format")
        if not self.bridge.ar_set_device_format(
            device_id,
            config["channels"],
            config["sample_rate"],
            config["bits"],
            int(config["encoding"] == "float"),
            config["container_bits"],
        ):
            raise BackendError(self._error())
        self.refresh()
        if self.last_error:
            raise BackendError("Format was applied, but device refresh failed: " + self.last_error)
        active = self.get_device(device_id)
        if active.channels != config["channels"] or active.sample_rate != config["sample_rate"]:
            return (
                "Windows saved the format, but the active mix format has not changed yet. "
                "Close apps using this endpoint and refresh devices. The matrix uses the active format."
            )
        return "Windows endpoint format applied and verified."

    def rename_device(self, device_id, name):
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or any(ord(c) < 32 for c in name):
            raise BackendError("Enter a name of 1–128 printable characters")
        self.get_device(device_id)
        if not self.capabilities()["device_rename"]:
            raise BackendError("Native rename unavailable")
        if not self.bridge.ar_rename_device(device_id, name.strip()):
            reason = self._error()
            if "administrator" not in reason.lower() or not getattr(sys, "frozen", False) or os.name != "nt":
                raise BackendError(reason)
            code = windows_vbcable._run_elevated(
                sys.executable, ["--rename-endpoint", device_id, name.strip()], Path(sys.executable).parent
            )
            if code:
                raise BackendError("Endpoint rename was cancelled or rejected by Windows")
        self.endpoint_aliases.pop(device_id, None)
        self.refresh()
        if self.get_device(device_id).name != name.strip():
            raise BackendError("Windows endpoint name has not updated; refresh and inspect Windows Sound")
        return "Windows endpoint name updated."

    def configure_cable(self, name):
        if self.bridge is None:
            raise BackendError("The native WASAPI bridge must be available before installing a cable")
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or any(ord(c) < 32 for c in name):
            raise BackendError("Enter a display name of 1–128 printable characters")
        self.refresh()
        cable = self._cable_outputs()
        code = 0
        if not cable:
            code = windows_vbcable.install()
            for _ in range(20):
                self.refresh()
                cable = self._cable_outputs()
                if cable:
                    break
                time.sleep(0.5)
        if not cable:
            raise BackendError(
                "VB-CABLE has no active playback endpoint yet. Restart Windows, then click Create again."
            )
        # Preserve vendor/Windows names. The legacy argument is validated
        # for API compatibility, but never renames or adds a local alias.
        self.refresh()
        return (
            "VB-CABLE is available. Windows reports a restart pending."
            if code == 3010
            else "Virtual output ready."
        )

    def _cable_outputs(self):
        return sorted(
            (
                d
                for d in self.devices.values()
                if d.kind == "output" and d.properties.get("virtual_driver") == "VB-CABLE"
            ),
            key=lambda d: (d.channels or 999, d.id),
        )

    def install_virtual_driver(self):
        return self.configure_cable("Virtual audio")

    def uninstall_virtual_driver(self):
        self.refresh()
        endpoints = {d.id for d in self.devices.values() if d.properties.get("virtual_driver") == "VB-CABLE"}
        if any(r.source_id in endpoints or r.destination_id in endpoints for r in self.routes.values()):
            raise BackendError("Remove routes using VB-CABLE before removing the shared driver")
        code = windows_vbcable.uninstall()
        self.endpoint_aliases = {k: v for k, v in self.endpoint_aliases.items() if k not in endpoints}
        self.refresh()
        return "Driver removal completed. Restart Windows to finish." if code == 3010 else "VB-CABLE removed."

    def set_route_delay(self, route_id, delay_ms, *, allow_restart=True):
        if not self.capabilities().get("route_delay"):
            raise BackendError("Rebuild the WASAPI DLL to enable synchronization delay controls")
        if type(delay_ms) is not int or not 0 <= delay_ms <= 10000:
            raise BackendError("Additional delay must be between 0 and 10000 ms")
        route = self.get_route_status(route_id)
        old_delay = route.delay_ms
        if not route.enabled or not self.transport_running:
            route.delay_ms = delay_ms
            return
        if route.enabled:
            self._validate_route(route)
        if route.enabled and self.has_live_delay_api and route.status == "connected":
            native_id, capture_input = self._native_source(route.source_id)
            destination = self.devices[route.destination_id].properties.get(
                "native_endpoint_id", route.destination_id
            )
            if self.bridge.ar_source_set_delay(native_id, int(capture_input), destination, delay_ms):
                route.delay_ms = delay_ms
                target = self.active_sessions.get(route.source_id, ())
                values = list(self.active_delays.get(route.source_id, (0,) * len(target)))
                if destination in target:
                    values[target.index(destination)] = delay_ms
                    self.active_delays[route.source_id] = tuple(values)
                self._read_stats()
                return
            if not allow_restart:
                raise BackendError(self._error())
        elif route.enabled and not allow_restart:
            raise BackendError(
                "This route needs a source restart; enable the restart option to apply the delay"
            )
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
            "virtual_driver": {
                "provider": "VB-CABLE",
                "origin": "https://www.vb-cable.com/",
                "donationware": "Donations are welcome: https://vb-audio.com/Services/licensing.htm",
                "present": any(
                    d.properties.get("virtual_driver") == "VB-CABLE" for d in self.devices.values()
                ),
                "arbitrary_device_creation": False,
            },
        }

    def close(self):
        if self.bridge:
            self.bridge.ar_close()
        self.active_sessions.clear()
        self.active_delays.clear()
        self.active_matrices.clear()
        self.source_endpoints.clear()
