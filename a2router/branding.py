"""Process-local Windows taskbar identity; no registry or shell settings writes."""

import ctypes
import sys


def prepare_windows_identity():
    if sys.platform == "win32":
        function = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        function.argtypes, function.restype = [ctypes.c_wchar_p], ctypes.c_long
        return function("vkr6.A2Router") == 0
    return False
