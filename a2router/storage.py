"""Strict, versioned desired state. OS module IDs are never persisted."""

import json
import os
import tempfile
from pathlib import Path
from uuid import UUID

from a2router.models import LAYOUTS, BackendError


def _uuid(value):
    if not isinstance(value, str):
        raise TypeError("ID must be a UUID string")
    UUID(value)
    return value


def validate(data):
    try:
        if not isinstance(data, dict) or set(data) != {"version", "virtual_devices", "routes"}:
            raise ValueError("Expected version, virtual_devices, and routes")
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("Unsupported configuration version")
        ids, pairs = set(), set()
        for key in ("virtual_devices", "routes"):
            if not isinstance(data[key], list) or len(data[key]) > 1000:
                raise ValueError("Definitions must be lists with at most 1000 entries")
            for item in data[key]:
                if not isinstance(item, dict):
                    raise TypeError("Invalid definition")
                ident = _uuid(item.get("id"))
                if ident in ids:
                    raise ValueError("Duplicate identifier")
                ids.add(ident)
                if key == "virtual_devices":
                    if set(item) != {"id", "name", "layout"}:
                        raise ValueError("Unknown virtual-device fields")
                    name = item["name"]
                    if (
                        not isinstance(name, str)
                        or not name.strip()
                        or len(name) > 128
                        or any(ord(c) < 32 for c in name)
                    ):
                        raise ValueError("Invalid device name")
                    if item["layout"] not in LAYOUTS:
                        raise ValueError("Unsupported layout")
                else:
                    if set(item) - {"delay_ms"} != {
                        "id",
                        "source_id",
                        "destination_id",
                        "enabled",
                        "monitoring_confirmed",
                        "channel_map",
                    }:
                        raise ValueError("Unknown or missing route fields")
                    for field in ("source_id", "destination_id"):
                        if not isinstance(item[field], str) or not item[field] or len(item[field]) > 2048:
                            raise ValueError("Invalid endpoint ID")
                    if type(item["enabled"]) is not bool or type(item["monitoring_confirmed"]) is not bool:
                        raise ValueError("Route states must be booleans")
                    delay = item.get("delay_ms", 0)
                    if type(delay) is not int or not 0 <= delay <= 10000:
                        raise ValueError("Delay must be an integer between 0 and 10000 ms")
                    if item["channel_map"] != []:
                        raise ValueError("Channel-level routing is not implemented")
                    pair = (item["source_id"], item["destination_id"])
                    if pair in pairs:
                        raise ValueError("Duplicate route")
                    pairs.add(pair)
        return data
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise BackendError(f"Invalid configuration: {exc}") from exc


def load(path):
    try:
        with open(path, encoding="utf-8") as stream:
            return validate(json.load(stream))
    except (OSError, ValueError) as exc:
        raise BackendError(f"Cannot load configuration: {exc}") from exc


def save(path, data):
    validate(data)  # Never touch an existing valid file if validation fails.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise BackendError(f"Cannot save configuration: {exc}") from exc
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
