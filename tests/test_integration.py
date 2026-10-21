"""Opt-in real server tests. All test routes terminate at owned silent virtual sinks."""

import os
import time
from uuid import uuid4

import pytest

from a2router.backends.linux_pipewire import PipeWireBackend
from a2router.controller import Controller
from a2router.models import LAYOUTS, VirtualDevice

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("A2ROUTER_INTEGRATION") != "1",
        reason="Set A2ROUTER_INTEGRATION=1 with a suitable audio server",
    ),
]


def monitor(config):
    return "source:" + config.device_id.removeprefix("sink:") + ".monitor"


def test_server_layouts_fanout_mixing_restore_cleanup(tmp_path):
    backend = PipeWireBackend(owner="test_" + uuid4().hex)
    backend.refresh()
    assert not backend.last_error, backend.last_error
    initial_names = set(backend.devices)
    definitions = []
    try:
        for layout in LAYOUTS:
            config = VirtualDevice("a2router 'test' \"" + layout + '"', layout)
            definitions.append(config)
            backend.create_virtual_device(config)
            assert backend.get_device(config.device_id).positions == LAYOUTS[layout]
            assert backend.get_device(config.device_id).name == config.name
            backend.create_virtual_device(config)
        stereo = next(v for v in definitions if v.layout == "stereo")
        for name in ("source B", "output A", "output B"):
            config = VirtualDevice("a2router test " + name)
            definitions.append(config)
            backend.create_virtual_device(config)
        source_b, output_a, output_b = definitions[-3:]
        routes = [
            backend.create_route(monitor(s), d.device_id)
            for s, d in ((stereo, output_a), (stereo, output_b), (source_b, output_a))
        ]
        for r in routes:
            assert r.status == "connected", r.error
            assert len(r.resource_ids) == 1
        for route in routes:
            backend.disable_route(route.id)
            backend.disable_route(route.id)
            assert not backend._find("route", route.id)
            backend.enable_route(route.id)
            assert route.status == "connected", route.error
        controller = Controller(backend)
        path = tmp_path / "integration.json"
        controller.save(path)
        resource_count = len([m for m in backend.modules if backend._owned(m)])
        # Fresh controller adopts the same modules, including all fanout routes.
        restarted = PipeWireBackend(owner=backend.owner)
        errors = Controller(restarted).load(path)
        assert errors == [], errors
        restarted.refresh()
        assert len([m for m in restarted.modules if restarted._owned(m)]) == resource_count
        assert all(r.status == "connected" for r in restarted.list_routes())
        # Verify actual PCM traverses a managed route, not just that a module exists.
        if os.environ.get("A2ROUTER_PCM_TEST") == "1":
            verify_pcm(stereo, output_b)
            verify_pcm(stereo, output_a, secondary=source_b)
        for route in routes:
            backend.remove_route(route.id)
            backend.remove_route(route.id)
        for config in reversed(definitions):
            backend.remove_virtual_device(config.id)
        backend.refresh()
        assert not any(backend._owned(m) for m in backend.modules)
        assert set(backend.devices) == initial_names
    finally:
        backend.cleanup_owned()
        assert not any(backend._owned(m) for m in backend.modules)


def verify_pcm(source, destination, secondary=None):
    """Distinct channel tones verify non-silent transport and channel ordering.

    This is a signal-path test with resampling allowed, not a bit-perfect claim.
    """
    import array
    import math
    import subprocess
    import tempfile

    rate = 48000
    values = array.array("f")
    for i in range(rate * 2):
        values.extend(
            (0.1 * math.sin(2 * math.pi * 431 * i / rate), 0.1 * math.sin(2 * math.pi * 997 * i / rate))
        )

    def play(config, pcm):
        return subprocess.run(
            [
                "pacat",
                "--playback",
                "--raw",
                "--format=float32le",
                "--rate=48000",
                "--channels=2",
                "--device=" + config.device_id.removeprefix("sink:"),
            ],
            input=pcm,
            capture_output=True,
            timeout=12,
            check=False,
        )

    with tempfile.TemporaryFile() as captured:
        recorder = subprocess.Popen(
            [
                "parec",
                "--raw",
                "--format=float32le",
                "--rate=48000",
                "--channels=2",
                "--device=" + monitor(destination).removeprefix("source:"),
            ],
            stdout=captured,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(0.3)
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(play, source, values.tobytes())
                second = None
                if secondary:
                    extra = array.array("f")
                    for i in range(rate * 2):
                        extra.extend(
                            (
                                0.1 * math.sin(2 * math.pi * 733 * i / rate),
                                0.1 * math.sin(2 * math.pi * 1291 * i / rate),
                            )
                        )
                    second = pool.submit(play, secondary, extra.tobytes())
                for task in (first, second):
                    if task:
                        result = task.result()
                        assert result.returncode == 0, result.stderr.decode()
            time.sleep(0.3)
        finally:
            recorder.terminate()
            recorder.wait(timeout=5)
        captured.seek(0)
        data = captured.read()
    samples = array.array("f")
    samples.frombytes(data[: len(data) // 8 * 8])
    assert len(samples) > 48000, "No captured PCM"

    # Correlation magnitude is independent of unknown route phase/delay.
    def power(channel, frequency):
        real = imag = 0.0
        for i, sample in enumerate(samples[channel::2]):
            real += sample * math.cos(2 * math.pi * frequency * i / rate)
            imag += sample * math.sin(2 * math.pi * frequency * i / rate)
        return real * real + imag * imag

    left, right = power(0, 431), power(1, 997)
    assert left > 1 and right > 1, "Managed route carried no detectable test tones"
    assert left > 10 * power(0, 997), "Left channel order/crosstalk failure"
    assert right > 10 * power(1, 431), "Right channel order/crosstalk failure"
    if secondary:
        assert power(0, 733) > 1 and power(1, 1291) > 1, "Second source was not mixed into destination"
        assert max(abs(v) for v in samples) < 0.3, "Unexpected clipping/gain on low-level test signals"


def test_gui_controls_real_server(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from a2router.ui import MainWindow

    app = QApplication.instance() or QApplication([])
    backend = PipeWireBackend(owner="test_" + uuid4().hex)
    backend.refresh()
    controller = Controller(backend)
    window = MainWindow(controller, tmp_path / "gui-session.json")

    def wait():
        deadline = time.monotonic() + 15
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert not window.busy

    try:
        window.show()
        wait()
        for name in ("GUI source", "GUI destination"):
            window.virtual_name.setText(name)
            window.create_virtual_button.click()
            wait()
            assert window.error.text() == backend.name, window.error.text()
        definitions = list(backend.virtual_devices.values())
        window.source.setCurrentIndex(window.source.findData(monitor(definitions[0])))
        window.destination.setCurrentIndex(window.destination.findData(definitions[1].device_id))
        window.add_route_button.click()
        wait()
        assert backend.list_routes()[0].status == "connected", window.error.text()
        window.route_tree.topLevelItem(0).setSelected(True)
        window.route_action("disable_route")
        wait()
        assert backend.list_routes()[0].status == "disabled"
        window.route_action("enable_route")
        wait()
        assert backend.list_routes()[0].status == "connected"
        window.route_action("remove_route")
        wait()
        assert not backend.list_routes()
        assert (tmp_path / "gui-session.json").exists()
    finally:
        wait()
        window.exit_application()
        deadline = time.monotonic() + 10
        while not window.executor._shutdown and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        backend.cleanup_owned()
        assert not any(backend._owned(m) for m in backend.modules)


def test_recovery_after_private_pulse_server_restart():
    if os.environ.get("A2ROUTER_PRIVATE_SERVER") != "1":
        pytest.skip("Daemon restart test only runs inside the private-server harness")
    import signal
    import subprocess
    import tempfile

    backend = PipeWireBackend(owner="test_" + uuid4().hex)
    backend.refresh()
    source, destination = [VirtualDevice("restart " + name) for name in ("source", "destination")]
    replacement = None
    with tempfile.TemporaryFile() as log:
        try:
            for config in (source, destination):
                backend.create_virtual_device(config)
            route = backend.create_route(monitor(source), destination.device_id)
            assert route.status == "connected", route.error
            os.kill(int(os.environ["A2ROUTER_PRIVATE_PULSE_PID"]), signal.SIGTERM)
            for _ in range(40):
                backend.refresh()
                if backend.last_error:
                    break
                time.sleep(0.05)
            assert backend.last_error and route.status == "pending"
            assert route.enabled and len(backend.virtual_devices) == 2
            replacement = subprocess.Popen(["pipewire-pulse"], stdout=log, stderr=log)
            for _ in range(50):
                backend.refresh()
                if not backend.last_error and route.status == "connected":
                    break
                time.sleep(0.1)
            assert route.status == "connected", (backend.last_error, route.error)
            assert len(backend._find("route", route.id)) == 1
            if os.environ.get("A2ROUTER_PCM_TEST") == "1":
                verify_pcm(source, destination)
        finally:
            if replacement:
                backend.cleanup_owned()
                assert not any(backend._owned(m) for m in backend.modules)
                replacement.terminate()
                replacement.wait(timeout=5)
