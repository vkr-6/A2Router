"""VB-CABLE is a shared vendor driver, not a source of arbitrary virtual devices."""

import ctypes
import os
import sys
from pathlib import Path

from a2router.models import BackendError


def payload_directory():
    if os.environ.get("A2ROUTER_VBCABLE_DIR"):
        return Path(os.environ["A2ROUTER_VBCABLE_DIR"]).expanduser().resolve()
    root = (
        Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    )
    return root / "vendor" / "vb-cable"


def install():
    """Request the official installer; endpoint discovery verifies availability later."""
    directory = payload_directory()
    executable = directory / "VBCABLE_Setup_x64.exe"
    if os.name != "nt" or not executable.is_file():
        raise BackendError("Install VB-CABLE with the A2Router Windows setup package")
    from ctypes import wintypes

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    result = shell.ShellExecuteW(None, "runas", str(executable), "-i -h", str(directory), 1)
    if not result or result <= 32:
        raise BackendError("VB-CABLE installer was cancelled or could not be started")
    return "VB-CABLE installer started. Finish installation and restart Windows, then refresh devices."
