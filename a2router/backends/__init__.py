import sys


def make_backend(mock=False):
    if mock:
        from .mock import MockBackend

        return MockBackend()
    if sys.platform == "linux":
        from .linux_pipewire import PipeWireBackend

        return PipeWireBackend()
    if sys.platform == "win32":
        from .windows import WindowsBackend

        return WindowsBackend()
    from a2router.models import BackendError

    raise BackendError("Supported platforms: Linux with PipeWire/PulseAudio, Windows with WASAPI bridge")
