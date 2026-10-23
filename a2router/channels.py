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
