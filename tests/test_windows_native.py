"""Opt-in real Windows DLL/probe tests; signal tests run only in the test VM."""

import array
import math
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from a2router.backends.windows import WindowsBackend

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("A2ROUTER_WASAPI_NATIVE") != "1",
    reason="Requires compiled WASAPI DLL on real Windows",
)


@pytest.fixture
def backend():
    backend = WindowsBackend()
    backend.refresh()
    assert not backend.last_error, backend.last_error
    yield backend
    backend.close()


def test_native_endpoint_discovery(backend):
    assert backend.bridge.ar_api_version() == 2
    assert all(device.kind in ("input", "output") for device in backend.list_devices())
    assert len({d.id for d in backend.list_devices()}) == len(backend.list_devices())
    for device in backend.list_devices():
        if device.channels is not None:
            assert device.channels > 0 and device.sample_rate > 0


def test_native_vm_fanout_fanin_pcm_and_input(backend, tmp_path):
    if os.environ.get("A2ROUTER_VM_AUDIO_TEST") != "1":
        pytest.skip("PCM emission/capture is confined to the disposable Windows VM")
    outputs = [
        d
        for d in backend.list_devices()
        if d.kind == "output" and d.channels == 2 and d.positions == ("front-left", "front-right")
    ]
    assert len(outputs) >= 4, "Four emulated stereo output endpoints required"
    source_a, source_b, dest_a, dest_b = outputs[:4]
    monitor = lambda device: "wasapi-loopback:" + device.id
    routes = [backend.create_route(monitor(source_a), d.id) for d in (dest_a, dest_b)]
    routes.append(backend.create_route(monitor(source_b), dest_a.id))
    assert all(r.status == "connected" for r in routes), [(r.status, r.error) for r in routes]
    assert len(backend.active_sessions) == 2
    root = Path(__file__).resolve().parents[1]
    probe = root / "build" / "Release" / "a2router_wasapi_probe.exe"
    if not probe.exists():
        probe = root / "build" / "a2router_wasapi_probe.exe"
    assert probe.exists(), "Build native Windows signal probe first"
    processes = []
    try:
        captures = []
        for index, dest in enumerate((dest_a, dest_b)):
            path = tmp_path / f"monitor-{index}.pcm"
            captures.append(path)
            processes.append(
                subprocess.Popen([str(probe), "record", dest.id, str(path), "4"], stderr=subprocess.PIPE)
            )
        time.sleep(0.4)
        tones = [
            subprocess.Popen(
                [str(probe), "tone", source.id, str(left), str(right), "2.5"], stderr=subprocess.PIPE
            )
            for source, left, right in ((source_a, 431, 997), (source_b, 733, 1291))
        ]
        processes.extend(tones)
        for process in processes:
            _, stderr = process.communicate(timeout=12)
            assert process.returncode == 0, stderr.decode(errors="replace")

        def power(samples, channel, frequency, rate):
            real = imag = 0.0
            for index, sample in enumerate(samples[channel::2]):
                real += sample * math.cos(2 * math.pi * frequency * index / rate)
                imag += sample * math.sin(2 * math.pi * frequency * index / rate)
            return real * real + imag * imag

        for index, path in enumerate(captures):
            data = path.read_bytes()
            rate, channels = struct.unpack("<II", data[:8])
            samples = array.array("f")
            samples.frombytes(data[8:])
            assert channels == 2 and len(samples) > rate
            assert power(samples, 0, 431, rate) > 1 and power(samples, 1, 997, rate) > 1, "No routed PCM"
            assert power(samples, 0, 431, rate) > 10 * power(samples, 0, 997, rate), (
                "Left/right channel order failure"
            )
            if index == 0:
                assert power(samples, 0, 733, rate) > 1 and power(samples, 1, 1291, rate) > 1, (
                    "Second source not mixed"
                )
            assert max(map(abs, samples)) < 0.3, "Unexpected gain/clipping on low-level tones"
        for route in routes:
            backend.disable_route(route.id)
            backend.disable_route(route.id)
            assert route.status == "disabled"
            backend.enable_route(route.id)
            assert route.status == "connected", route.error
        inputs = [d for d in backend.list_devices() if d.kind == "input" and not d.monitor_of]
        assert inputs, "Emulated capture endpoint required"
        microphone = backend.create_route(inputs[0].id, dest_b.id, monitoring_confirmed=True)
        assert microphone.status == "connected", microphone.error
        for route in list(backend.list_routes()):
            backend.remove_route(route.id)
        assert not backend.active_sessions
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def test_native_invalid_endpoint_and_direction_are_rejected(backend):
    outputs = [device for device in backend.list_devices() if device.kind == "output"]
    if not outputs:
        pytest.skip("No active render endpoint available for native failure validation")
    assert backend.bridge.ar_source_start("a2router-invalid-endpoint", 0, outputs[0].id) == 0
    assert b"unavailable" in backend.bridge.ar_error()
    assert backend.bridge.ar_source_start(outputs[0].id, 1, outputs[0].id) == 0
    assert b"wrong data flow" in backend.bridge.ar_error()
    assert not any(
        session.get("running") for session in __import__("json").loads(backend.bridge.ar_stats())["sessions"]
    )
