import os
import threading
from dataclasses import asdict
from pathlib import Path

from a2router import storage
from a2router.models import BackendError, Route, VirtualDevice


def config_dir():
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "a2router"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "a2router"


class Controller:
    def __init__(self, backend):
        self.backend = backend
        self.virtual_definitions = {}
        self.calibration = None
        self._emergency = threading.Event()

    def snapshot(self):
        self.virtual_definitions.update(self.backend.virtual_devices)
        return {
            **({"calibration": self.calibration} if self.calibration is not None else {}),
            "version": 1,
            "endpoint_aliases": dict(self.backend.endpoint_aliases),
            "virtual_devices": [asdict(v) for v in self.virtual_definitions.values()],
            "routes": [
                {k: v for k, v in asdict(r).items() if k not in ("status", "error", "resource_ids")}
                for r in self.backend.list_routes()
            ],
        }

    def refresh(self):
        self.backend.refresh()
        created = False
        for config in self.virtual_definitions.values():
            if not self.backend.capabilities()["virtual_devices"]:
                continue  # Keep unsupported definitions without retrying an impossible operation each poll.
            if config.id not in self.backend.virtual_devices:
                try:
                    self.backend.create_virtual_device(config)
                    created = True
                except BackendError as exc:
                    self.backend.last_error = str(exc)
        if created:
            self.backend.refresh()

    def save(self, path):
        storage.save(path, self.snapshot())

    def restore(self, data, activate=True):
        storage.validate(data)
        errors = []
        # Preflight ID conflicts before performing any external changes.
        for item in data["virtual_devices"]:
            old = self.virtual_definitions.get(item["id"]) or self.backend.virtual_devices.get(item["id"])
            if old and asdict(old) != item:
                raise BackendError("Virtual ID conflict; remove the old definition first")
        for item in data["routes"]:
            old = self.backend.routes.get(item["id"])
            if old and (old.source_id, old.destination_id) != (item["source_id"], item["destination_id"]):
                raise BackendError("Route ID conflict")
        existing_pairs = {(r.source_id, r.destination_id): r.id for r in self.backend.list_routes()}
        for item in data["routes"]:
            pair = (item["source_id"], item["destination_id"])
            if pair in existing_pairs and existing_pairs[pair] != item["id"]:
                raise BackendError("Profile duplicates an existing route under a different ID")
        self.calibration = data.get("calibration")
        self.backend.endpoint_aliases.update(data.get("endpoint_aliases", {}))
        if not activate:
            for item in data["virtual_devices"]:
                config = VirtualDevice(**item)
                self.virtual_definitions[config.id] = config
                self.backend.virtual_devices[config.id] = config
            for item in data["routes"]:
                self.backend.routes[item["id"]] = Route(**item)
            self.backend.refresh(reconcile=False)
            return []
        self.backend.refresh()
        for item in data["virtual_devices"]:
            config = VirtualDevice(**item)
            self.virtual_definitions[config.id] = config
            try:
                self.backend.create_virtual_device(config)
            except BackendError as exc:
                errors.append(f"{config.name}: {exc}")
        self.backend.refresh()
        for item in data["routes"]:
            try:
                route = self.backend.create_route(
                    item["source_id"],
                    item["destination_id"],
                    route_id=item["id"],
                    enabled=item["enabled"],
                    monitoring_confirmed=item["monitoring_confirmed"],
                    allow_missing=True,
                    delay_ms=item.get("delay_ms", 0),
                    volume=item.get("volume", 1.0),
                    muted=item.get("muted", False),
                    channel_map=item.get("channel_map", []),
                )
                route.volume, route.muted = item.get("volume", 1.0), item.get("muted", False)
                route.delay_ms = item.get("delay_ms", 0)
                route.channel_map = [dict(connection) for connection in item.get("channel_map", [])]
                route.monitoring_confirmed = item["monitoring_confirmed"]
                if item["enabled"]:
                    self.backend.enable_route(route.id)
                else:
                    self.backend.disable_route(route.id)
                if route.error:
                    errors.append(f"{route.id}: {route.error}")
            except BackendError as exc:
                # Retain desired definitions even when current layouts or safety
                # checks prevent connection. Reconciliation must validate again.
                if item["id"] not in self.backend.routes:
                    route = Route(**item)
                    route.status, route.error = "error", str(exc)
                    self.backend.routes[route.id] = route
                errors.append(f"{item['id']}: {exc}")
        return errors

    def load(self, path, activate=True):
        return self.restore(storage.load(path), activate=activate)

    def measure_calibration(self, microphone_id, outputs, reference_id, passes, level_db, channel, progress):
        from a2router.calibration import check_request, measure, validate_result

        check_request(self.backend, microphone_id, outputs, reference_id, passes, level_db, channel)
        self._emergency.clear()
        running = self.backend.transport_running
        self.pause_routes()
        failure = None
        try:
            result = measure(
                self.backend, microphone_id, outputs, reference_id, passes, level_db, channel, progress
            )
            self.calibration = validate_result(result)
        except Exception as exc:  # noqa: BLE001 — routing must be restored after analysis/native failures
            failure = exc
        finally:
            try:
                if running:
                    self.resume_routes(clear_emergency=False)
            except BackendError as exc:
                if failure is not None:
                    raise BackendError(f"{failure}; restoring routing failed: {exc}") from exc
                raise BackendError(f"Measurement finished; restoring routing failed: {exc}") from exc
        if failure is not None:
            raise failure
        return "Measurement complete; review compensation before applying"

    def apply_calibration(self, delays, allow_restart=False):
        if self.calibration is None:
            raise BackendError("Measure or load calibration first")
        from a2router.calibration import validate_result

        validate_result(self.calibration)
        outputs = {row["device_id"]: row for row in self.calibration["outputs"]}
        if not isinstance(delays, dict) or set(delays) != set(outputs):
            raise BackendError("Compensation must include exactly the measured outputs")
        if any(type(value) is not int or not 0 <= value <= 10000 for value in delays.values()):
            raise BackendError("Native delay requests require integer milliseconds from 0 to 10000")
        if any(row["confidence"] < 0.35 for row in outputs.values()):
            raise BackendError("Calibration confidence is too low to apply")
        routes = [r for r in self.backend.list_routes() if r.destination_id in outputs]
        if {r.destination_id for r in routes} != set(outputs):
            raise BackendError("Add routes to every measured output before applying compensation")
        previous = {r.id: r.delay_ms for r in routes}
        applied = []
        try:
            for route in routes:
                self.backend.set_route_delay(
                    route.id, delays[route.destination_id], allow_restart=allow_restart
                )
                applied.append(route.id)
        except BackendError as exc:
            errors = []
            for ident in reversed(applied):
                try:
                    self.backend.set_route_delay(ident, previous[ident], allow_restart=allow_restart)
                except BackendError as rollback:
                    errors.append(str(rollback))
            raise BackendError(
                f"Compensation failed: {exc}; "
                + ("rollback failed: " + "; ".join(errors) if errors else "previous requests restored")
            ) from exc
        return "Compensation requests applied; inspect route buffering for convergence"

    def pause_routes(self):
        """Stop managed transport without changing profile enabled states."""
        self.backend.transport_running = False
        errors = []
        for route in self.backend.list_routes():
            try:
                self.backend._disconnect(route)
                route.status = "stopped" if route.enabled else "disabled"
            except BackendError as exc:
                route.status, route.error = "error", str(exc)
                errors.append(str(exc))
        if errors:
            raise BackendError("; ".join(errors))

    def request_emergency_stop(self):
        # Only thread-safe flags/native cancellation are touched here.
        self._emergency.set()
        if hasattr(self.backend, "cancel_calibration"):
            self.backend.cancel_calibration()

    def resume_routes(self, *, clear_emergency=True):
        if clear_emergency:
            self._emergency.clear()
        elif self._emergency.is_set():
            return
        self.backend.transport_running = True
        self.refresh()
        if not clear_emergency and self._emergency.is_set():
            self.pause_routes()
            return
        errors = [r.error for r in self.backend.list_routes() if r.enabled and r.error]
        if errors:
            raise BackendError("; ".join(errors))

    def replace_profile(self, data):
        """Validate first; retain unrelated virtual devices and roll back routes on failure.

        Unavailable endpoints remain pending. This does not uninstall a shared driver
        or delete server virtual sinks omitted by the new profile.
        """
        from copy import deepcopy

        storage.validate(data)
        previous = deepcopy(self.snapshot())
        was_running = self.backend.transport_running
        self.pause_routes()
        self.backend.routes.clear()
        try:
            self.backend.endpoint_aliases = dict(data.get("endpoint_aliases", {}))
            errors = self.restore(data, activate=was_running)
            if was_running:
                self.backend.transport_running = True
                self.refresh()
            return errors
        except Exception:
            self.backend.routes.clear()
            self.backend.endpoint_aliases = dict(previous.get("endpoint_aliases", {}))
            self.restore(previous, activate=False)
            self.backend.transport_running = was_running
            if was_running:
                self.refresh()
            raise

    def start_routes(self):
        for route in self.backend.list_routes():
            self.backend.enable_route(route.id)

    def stop_routes(self):
        errors = []
        for route in self.backend.list_routes():
            try:
                self.backend.disable_route(route.id)
            except BackendError as exc:
                errors.append(str(exc))
        if errors:
            raise BackendError("; ".join(errors))


class SessionLock:
    """One state-owning controller per user; released automatically after crashes."""

    def __init__(self, path):
        self.path = Path(path)
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.stream.seek(0)
                self.stream.write(b"0")
                self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise BackendError("Another a2router controller is using this configuration") from exc
        return self

    def __exit__(self, *_):
        self.stream.close()
