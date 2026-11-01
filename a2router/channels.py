"""Validated channel matrix definitions; all sample processing stays in C++."""

import math

from a2router.models import BackendError


def validate_channel_map(mapping, source_channels=None, destination_channels=None):
    if not isinstance(mapping, list) or len(mapping) > 1024:
        raise BackendError("Channel mapping must be a list of at most 1024 connections")
    pairs = set()
    for item in mapping:
        if not isinstance(item, dict) or set(item) != {"source", "destination", "gain"}:
            raise BackendError("Each channel connection requires source, destination and gain")
        for key, count in (("source", source_channels), ("destination", destination_channels)):
            index = item[key]
            if type(index) is not int or not 0 <= index < 64 or (count is not None and index >= count):
                raise BackendError(f"Invalid {key} channel index")
        gain = item["gain"]
        if type(gain) not in (int, float) or not math.isfinite(gain) or not -4 <= gain <= 4:
            raise BackendError("Channel gain must be finite and between -4 and 4")
        pair = (item["source"], item["destination"])
        if pair in pairs:
            raise BackendError("Duplicate channel connection; adjust its gain instead")
        pairs.add(pair)
    return mapping


def conversion_preset(name, source_positions, destination_positions, *, level="preserve"):
    """Explicit channel conversion using reported positions and selected headroom.

    The 5.1 fold-down uses ITU-R BS.775-style -3 dB centre/surround
    contributions. Additional 7.1 surround pairs are an explicit extension.
    LFE is intentionally excluded; no bass management is synthesized.
    """
    if level not in ("preserve", "headroom", "normalize"):
        raise BackendError("Unknown conversion level mode")

    def finish(mapping):
        scale = 10 ** (-3 / 20) if level == "headroom" else 1.0
        if level == "normalize":
            total = max(
                (
                    sum(abs(c["gain"]) for c in mapping if c["destination"] == output)
                    for output in range(len(destination))
                ),
                default=1.0,
            )
            scale = 1 / max(1.0, total)
        return validate_channel_map(
            [{**c, "gain": c["gain"] * scale} for c in mapping], len(source), len(destination)
        )

    aliases = {"back-left": "rear-left", "back-right": "rear-right", "low-frequency": "lfe"}
    source = [aliases.get(p, p) for p in source_positions]
    destination = [aliases.get(p, p) for p in destination_positions]
    if (
        not source
        or not destination
        or len(set(source)) != len(source)
        or len(set(destination)) != len(destination)
    ):
        raise BackendError("Conversion requires unique, reported channel positions")
    matrix = []

    def add(s, d, gain):
        if s in source and d in destination:
            matrix.append({"source": source.index(s), "destination": destination.index(d), "gain": gain})

    if name == "Upmix stereo → surround":
        if (
            set(source) != {"front-left", "front-right"}
            or len(destination) not in (6, 8)
            or not {"front-left", "front-right", "front-center", "lfe"} <= set(destination)
        ):
            raise BackendError("Stereo upmix requires reported stereo and 5.1/7.1 destination positions")
        if set(destination) - {
            "front-left",
            "front-right",
            "front-center",
            "lfe",
            "rear-left",
            "rear-right",
            "side-left",
            "side-right",
        }:
            raise BackendError("Unsupported surround positions; use an explicit custom map")
        add("front-left", "front-left", 1)
        add("front-right", "front-right", 1)
        add("front-left", "front-center", 0.5)
        add("front-right", "front-center", 0.5)
        for left, right in [("rear-left", "rear-right"), ("side-left", "side-right")]:
            add("front-left", left, 0.5)
            add("front-right", right, 0.5)
        return finish(matrix)
    mono = name == "Downmix to mono"
    if name not in ("Downmix to stereo", "Downmix to mono"):
        raise BackendError("Unknown conversion preset")
    if (not mono and set(destination) != {"front-left", "front-right"}) or (
        mono and destination not in (["mono"], ["front-center"])
    ):
        raise BackendError("Choose an actual mono or stereo destination for this downmix")
    allowed = {
        "front-left",
        "front-right",
        "front-center",
        "mono",
        "lfe",
        "rear-left",
        "rear-right",
        "side-left",
        "side-right",
    }
    if set(source) - allowed:
        raise BackendError("Unknown source positions; no guessed downmix is performed")
    coefficients = {}
    for index, position in enumerate(source):
        if position == "lfe":
            continue
        if mono:
            coefficient = (
                1.0
                if position == "mono" or len(source) == 1
                else math.sqrt(0.5)
                if position == "front-center"
                else 0.5
                if position in ("front-left", "front-right")
                else math.sqrt(0.5) / 2
            )
            coefficients[(index, 0)] = coefficient
        else:
            targets = [0] if position.endswith("left") else [1] if position.endswith("right") else [0, 1]
            for channel in targets:
                dest = destination.index("front-left" if channel == 0 else "front-right")
                coefficients[(index, dest)] = (
                    1.0 if position in ("front-left", "front-right") else math.sqrt(0.5)
                )
    if not coefficients:
        raise BackendError("No non-LFE source channels to mix")
    matrix = [{"source": s, "destination": d, "gain": g} for (s, d), g in coefficients.items()]
    return finish(matrix)
