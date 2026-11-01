"""Load the actual Windows bridge without opening endpoints or starting audio."""

import ctypes
import json
import sys


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: check_bridge.py PATH_TO_WASAPI_DLL")
    bridge = ctypes.CDLL(sys.argv[1])
    for name in ("ar_api_version", "ar_vbcable_discovery_version"):
        function = getattr(bridge, name)
        function.argtypes = []
        function.restype = ctypes.c_int
    if bridge.ar_api_version() != 2 or bridge.ar_vbcable_discovery_version() != 1:
        raise SystemExit("Unexpected native bridge ABI; rebuild the DLL")
    if not hasattr(bridge, "ar_source_start_delays"):
        raise SystemExit("Native bridge is missing the synchronization export")
    if not hasattr(bridge, "ar_source_set_delay"):
        raise SystemExit("Native bridge is missing live delay control")
    if not hasattr(bridge, "ar_source_start_matrix"):
        raise SystemExit("Native bridge is missing channel matrix routing")
    for name in (
        "ar_controls",
        "ar_set_device_volume",
        "ar_set_device_mute",
        "ar_device_formats",
        "ar_set_device_format",
        "ar_rename_device",
    ):
        if not hasattr(bridge, name):
            raise SystemExit(f"Native bridge is missing {name}")
    for name in (
        "ar_routing_controls_version",
        "ar_calibration_version",
        "ar_application_api_version",
        "ar_live_matrix_version",
    ):
        function = getattr(bridge, name)
        function.argtypes, function.restype = [], ctypes.c_int
        if function() != 1:
            raise SystemExit(f"Unsupported native extension: {name}")
    for name in (
        "ar_application_capture_supported",
        "ar_applications",
        "ar_source_set_matrix",
        "ar_source_start_config",
        "ar_source_set_volume",
        "ar_calibration_record",
        "ar_calibration_reset",
        "ar_calibration_cancel",
    ):
        if not hasattr(bridge, name):
            raise SystemExit(f"Native bridge is missing {name}")
    print(json.dumps({"native_bridge_api": 2, "vbcable_discovery_api": 1, "delay_export": True}))


if __name__ == "__main__":
    main()
