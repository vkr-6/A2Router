"""Control of real root-enumerated Windows audio devices; no simulated endpoints."""

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from a2router.models import BackendError


def manager_path():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2] / "build"))
    candidates = [root / "a2router_device_manager.exe", root / "Release" / "a2router_device_manager.exe"]
    return next((p for p in candidates if p.is_file()), candidates[0])


def driver_path():
    if os.environ.get("A2ROUTER_DRIVER_INF"):
        return Path(os.environ["A2ROUTER_DRIVER_INF"]).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "driver" / "A2RouterAudio.inf"
    return Path(__file__).resolve().parents[2] / "build" / "windows-driver" / "package" / "A2RouterAudio.inf"


class WindowsVirtualDevices:
    def __init__(self):
        self.reboot_required = False

    def available(self):
        inf = driver_path()
        return (
            os.name == "nt"
            and manager_path().is_file()
            and all(
                (inf.parent / filename).is_file()
                for filename in (inf.name, "A2RouterAudio.sys", "A2RouterAudio.cat")
            )
        )

    def diagnostics(self):
        return {
            "manager": str(manager_path()),
            "inf": str(driver_path()),
            "package_present": self.available(),
            "signature_status": "Windows validates the catalog during installation; not pre-verified",
            "reboot_required": self.reboot_required,
            "status": "UNTESTED driver integration; requires a signed package and UAC approval",
        }

    def _run(self, *args):
        if os.name != "nt" or not manager_path().is_file():
            raise BackendError("Build a2router_device_manager.exe with CMake first")
        from ctypes import wintypes

        class ShellExecuteInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIcon", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        shell = ctypes.WinDLL("shell32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
        shell.ShellExecuteExW.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        info = ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x40 | 0x100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
        info.lpVerb = "runas"
        info.lpFile = str(manager_path())
        info.lpParameters = subprocess.list2cmdline(list(args))
        info.nShow = 0
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            raise BackendError(
                f"Driver operation cancelled or blocked: {ctypes.WinError(ctypes.get_last_error())}"
            )
        try:
            # Worker thread only. Do not terminate an install in the middle.
            wait = kernel.WaitForSingleObject(info.hProcess, 180_000)
            if wait != 0:
                raise BackendError(
                    "Driver operation has not completed; inspect Device Manager before retrying"
                )
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
                raise BackendError(str(ctypes.WinError(ctypes.get_last_error())))
            if code.value == 3010:
                self.reboot_required = True
                return
            if code.value:
                raise BackendError(
                    f"Windows driver operation failed ({code.value:#x}): {ctypes.FormatError(code.value)}. "
                    "Inspect %WINDIR%\\inf\\setupapi.dev.log for signature/installation details."
                )
        finally:
            kernel.CloseHandle(info.hProcess)

    def create(self, config):
        UUID(config.id)
        if config.layout != "stereo":
            raise BackendError(
                "The Windows a2router driver currently supports stereo, 48 kHz, 16-bit PCM only"
            )
        if not self.available():
            raise BackendError("Build and sign the driver package first; see drivers/windows/README.md")
        self.reboot_required = False
        self._run("create", config.id, config.name, str(driver_path()))

    def remove(self, config):
        UUID(config.id)
        self._run("remove", config.id)
