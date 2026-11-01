"""On-demand official VB-CABLE installer; no fabricated endpoint instances."""

import ctypes
import os
import subprocess
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


def _run_elevated(executable, arguments, directory):
    """Wait on the elevated process on the backend worker, keeping Qt responsive."""
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
    info.lpVerb, info.lpFile = "runas", executable
    info.lpParameters = subprocess.list2cmdline(arguments)
    info.lpDirectory, info.nShow = str(directory), 0
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    initialized = ole.CoInitializeEx(None, 6)  # STA | DISABLE_OLE1DDE, on this worker only.
    if initialized < 0 and initialized & 0xFFFFFFFF != 0x80010106:
        raise BackendError("Cannot initialize Windows shell services")
    try:
        if not shell.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
            raise BackendError("Driver operation was cancelled or could not start")
        try:
            if kernel.WaitForSingleObject(info.hProcess, 300000) != 0:
                raise BackendError(
                    "Driver installer is still running or could not be observed. Finish it before retrying."
                )
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
                raise BackendError("Cannot read driver installer result")
            return code.value
        finally:
            kernel.CloseHandle(info.hProcess)
    finally:
        if initialized >= 0:
            ole.CoUninitialize()


def _run(uninstall=False):
    directory = payload_directory()
    helper = directory.parent / "install-vbcable.ps1"
    if not helper.is_file():
        helper = Path(__file__).resolve().parents[2] / "tools/windows/install-vbcable.ps1"
    if os.name != "nt" or not helper.is_file() or not (directory / "VBCABLE_Setup_x64.exe").is_file():
        raise BackendError("Extract the complete A2Router portable ZIP, including its vendor folder")
    powershell = str(
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    arguments = [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(helper),
        "-Directory",
        str(directory),
    ]
    if uninstall:
        arguments.append("-Uninstall")
    code = _run_elevated(powershell, arguments, directory)
    if code not in (0, 3010):
        raise BackendError("VB-CABLE operation failed. See %TEMP%\\A2Router-VBCABLE-install.log")
    return code


def install():
    return _run()


def uninstall():
    return _run(uninstall=True)


def open_configuration():
    if os.name != "nt":
        raise BackendError("Windows sound configuration is only available on Windows")
    # Documented Sound control panel: Configure sets speakers, Properties sets
    # name and active format. No undocumented IPolicyConfig/registry writes.
    subprocess.Popen(
        [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/control.exe"), "mmsys.cpl", ",,0"]
    )


def open_driver_configuration():
    """Open only the verified vendor control panel, never the setup executable."""
    if os.name != "nt":
        raise BackendError("The VB-CABLE control panel is only available on Windows")
    import hashlib

    panel = payload_directory() / "VBCABLE_ControlPanel.exe"
    if not panel.is_file():
        raise BackendError("Extract the portable vendor folder to use the VB-CABLE control panel")
    if (
        hashlib.sha256(panel.read_bytes()).hexdigest()
        != "f5b44706fe7ba2eed0516dee791f826dc7a9891e997f6ce9704e2899300b14ff"
    ):
        raise BackendError("VB-CABLE control panel differs from the verified vendor package")
    subprocess.Popen([str(panel)], cwd=panel.parent)
    return "In the VB-CABLE panel menu, enable Windows Volume Control for the Windows sound slider."
