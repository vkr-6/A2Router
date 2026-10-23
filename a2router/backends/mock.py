from a2router.backends.base import AudioBackend
from a2router.models import LAYOUTS, Device


class MockBackend(AudioBackend):
    name = "SIMULATED — deterministic mock"

    def __init__(self):
        super().__init__()
        for ident, kind in [("mic", "input"), ("speakers", "output"), ("headphones", "output")]:
            self.devices[ident] = Device(
                ident,
                ident.title(),
                kind,
                False,
                channels=2,
                positions=LAYOUTS["stereo"],
                sample_rate=48000,
                state="IDLE",
            )
        self.devices["speakers.monitor"] = Device(
            "speakers.monitor",
            "Speakers monitor",
            "input",
            True,
            channels=2,
            positions=LAYOUTS["stereo"],
            monitor_of="speakers",
        )
        self.resources = set()

    def capabilities(self):
        return {**super().capabilities(), "channel_routing": True}

    def refresh(self, reconcile=True):
        if not reconcile:
            for route in self.routes.values():
                route.status = (
                    "connected"
                    if route.id in self.resources
                    else ("pending" if route.enabled else "disabled")
                )
            return
        for route in self.routes.values():
            if route.source_id not in self.devices or route.destination_id not in self.devices:
                self._disconnect(route)
            self._reconcile_route(route)

    def _connect(self, route):
        self.resources.add(route.id)
        route.resource_ids = [route.id]

    def _disconnect(self, route):
        self.resources.discard(route.id)
        route.resource_ids = []

    def _create_virtual(self, config):
        positions = LAYOUTS[config.layout]
        self.devices[config.device_id] = Device(
            config.device_id,
            config.name,
            "output",
            True,
            channels=len(positions),
            positions=positions,
            state="IDLE",
        )
        ident = "source:" + config.device_id.removeprefix("sink:") + ".monitor"
        self.devices[ident] = Device(
            ident,
            config.name + " monitor",
            "input",
            True,
            channels=len(positions),
            positions=positions,
            monitor_of=config.device_id,
        )

    def _remove_virtual(self, config):
        self.devices.pop(config.device_id, None)
        self.devices.pop("source:" + config.device_id.removeprefix("sink:") + ".monitor", None)
