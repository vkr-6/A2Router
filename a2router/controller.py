import os
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

    def snapshot(self):
        self.virtual_definitions.update(self.backend.virtual_devices)
        return {
            "version": 1,
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
                )
                route.delay_ms = item.get("delay_ms", 0)
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
