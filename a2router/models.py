from dataclasses import dataclass, field
from uuid import uuid4

LAYOUTS = {
    "mono": ("mono",),
    "stereo": ("front-left", "front-right"),
    "5.1": ("front-left", "front-right", "rear-left", "rear-right", "front-center", "lfe"),
    "7.1": (
        "front-left",
        "front-right",
        "rear-left",
        "rear-right",
        "front-center",
        "lfe",
        "side-left",
        "side-right",
    ),
}


class BackendError(RuntimeError):
    """Recoverable backend or configuration failure, suitable for display."""


@dataclass
class Device:
    id: str
    name: str
    kind: str  # input / output; output monitors are separate input endpoints
    virtual: bool | None = None
    default: bool = False
    channels: int | None = None
    positions: tuple[str, ...] = ()
    sample_rate: int | None = None
    sample_format: str | None = None
    state: str = "unknown"
    monitor_of: str | None = None
    latency: dict = field(default_factory=dict)
    properties: dict = field(default_factory=dict)


@dataclass
class VirtualDevice:
    name: str
    layout: str = "stereo"
    id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def device_id(self):
        return "sink:a2router_v_" + self.id.replace("-", "")


@dataclass
class Route:
    source_id: str
    destination_id: str
    id: str = field(default_factory=lambda: str(uuid4()))
    enabled: bool = True
    monitoring_confirmed: bool = False
    channel_map: list = field(default_factory=list)  # {source, destination, gain}; zero-based channels
    status: str = "pending"
    error: str = ""
    resource_ids: list[str] = field(default_factory=list)
    volume: float = 1.0  # Native per-stream gain, independent of system endpoint volume.
    muted: bool = False
    delay_ms: int = 0  # Windows native per-output additional buffering; 0 preserves old profiles.
