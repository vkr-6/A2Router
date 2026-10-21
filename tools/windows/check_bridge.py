"""Load the actual Windows bridge without opening endpoints or starting audio."""

import ctypes
import json
import sys


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: check_bridge.py PATH_TO_WASAPI_DLL")
    bridge = ctypes.CDLL(sys.argv[1])
    for name in ("ar_api_version", "ar_virtual_discovery_version"):
        function = getattr(bridge, name)
        function.argtypes = []
        function.restype = ctypes.c_int
    if bridge.ar_api_version() != 2 or bridge.ar_virtual_discovery_version() != 1:
        raise SystemExit("Unexpected native bridge ABI; rebuild the DLL")
    if not hasattr(bridge, "ar_source_start_delays"):
        raise SystemExit("Native bridge is missing the synchronization export")
    print(json.dumps({"native_bridge_api": 2, "virtual_discovery_api": 1, "delay_export": True}))


if __name__ == "__main__":
    main()
