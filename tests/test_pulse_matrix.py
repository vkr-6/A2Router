"""Real channel routing on the opt-in isolated PulseAudio test server."""

import os
import time
from uuid import uuid4

import pytest

from a2router.backends.linux_pipewire import PipeWireBackend
from a2router.models import LAYOUTS, BackendError, VirtualDevice

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("A2ROUTER_PULSE_MATRIX_TEST") != "1", reason="Use run_private_pulse.py"
    ),
]


def test_real_pulse_channel_remapping_and_lifecycle(tmp_path):
    backend = PipeWireBackend(owner="test_" + uuid4().hex)
    backend.refresh()
    assert backend.capabilities()["channel_routing"]
    source, destination = VirtualDevice("Matrix source"), VirtualDevice("Matrix destination")
    try:
        for definition in (source, destination):
            backend.create_virtual_device(definition)
        defaults = (backend.server.get("default_sink_name"), backend.server.get("default_source_name"))
        route = backend.create_route(
            "source:" + source.device_id.removeprefix("sink:") + ".monitor",
            destination.device_id,
            channel_map=[
                {"source": 0, "destination": 1, "gain": 1},
                {"source": 1, "destination": 0, "gain": 1},
            ],
        )
        assert route.status == "connected", route.error
        assert (
            backend.server.get("default_sink_name"),
            backend.server.get("default_source_name"),
        ) == defaults
        assert len(route.resource_ids) == 2
        verify_mapping(source, destination, swapped=True)
        assert not any("a2router_matrix_" in ident for ident in backend.devices)
        from a2router.controller import Controller

        Controller(backend).save(tmp_path / "matrix.json")
        restored = PipeWireBackend(owner=backend.owner)
        restored.refresh(reconcile=False)
        assert not Controller(restored).load(tmp_path / "matrix.json")
        assert len(restored._find("matrix", route.id)) == 2
        resources = route.resource_ids.copy()
        backend.refresh()
        assert route.resource_ids == resources
        backend.refresh(reconcile=False)
        assert route.status == "connected"
        backend.set_route_channel_map(
            route.id,
            [
                {"source": 0, "destination": 0, "gain": 1},
                {"source": 0, "destination": 1, "gain": 1},
            ],
        )
        assert len(route.resource_ids) == 4
        verify_mapping(source, destination, duplicate=True)
        backend.disable_route(route.id)
        assert not backend._find("matrix", route.id)
        backend.enable_route(route.id)
        assert route.status == "connected"
        backend.remove_route(route.id)
        assert not backend._find("matrix", route.id)
    finally:
        backend.cleanup_owned()
        assert not any(backend._owned(m) for m in backend.modules)


def verify_mapping(source, destination, swapped=False, duplicate=False, expected=None):
    import subprocess
    import tempfile

    import numpy as np

    rate = 48000
    t = np.arange(rate * 3) / rate
    channels = len(LAYOUTS[source.layout])
    frequencies = [431, 997, 1291, 1597, 1901, 2309][:channels]
    pcm = np.column_stack([0.1 * np.sin(2 * np.pi * frequency * t) for frequency in frequencies]).astype(
        "<f4"
    )
    if expected is None:
        expected = [[0], [0]] if duplicate else [[1], [0]] if swapped else [[i] for i in range(channels)]
    channel_args = [f"--channels={channels}", "--channel-map=" + ",".join(LAYOUTS[source.layout])]
    with tempfile.TemporaryFile() as recording:
        capture = subprocess.Popen(
            [
                "parec",
                "--device=" + destination.device_id.removeprefix("sink:") + ".monitor",
                "--format=float32le",
                *channel_args,
                "--rate=48000",
                "--latency-msec=20",
            ],
            stdout=recording,
        )
        try:
            time.sleep(0.2)
            subprocess.run(
                [
                    "pacat",
                    "--playback",
                    "--device=" + source.device_id.removeprefix("sink:"),
                    "--format=float32le",
                    *channel_args,
                    "--rate=48000",
                    "--latency-msec=20",
                ],
                input=pcm.tobytes(),
                check=True,
                timeout=10,
            )
        finally:
            capture.terminate()
            capture.wait(timeout=5)
        recording.seek(0)
        data = np.frombuffer(recording.read(), dtype="<f4").reshape(-1, channels)
        assert len(data) > rate
        for channel in range(channels):
            signal = data[:, channel]
            if not expected[channel]:
                assert np.max(np.abs(signal)) < 0.002
                continue
            assert np.max(np.abs(signal)) > 0.05
            spectrum = np.abs(np.fft.rfft(signal))
            hz = np.fft.rfftfreq(len(signal), 1 / rate)
            powers = [max(spectrum[abs(hz - f) < 3]) for f in frequencies]
            wanted = [powers[i] for i in expected[channel]]
            assert min(wanted) > max(spectrum) * 0.2, (channel, powers)
            assert all(powers[i] < min(wanted) * 0.08 for i in range(channels) if i not in expected[channel])


def test_six_channel_mapping_and_summing():
    backend = PipeWireBackend(owner="test_" + uuid4().hex)
    backend.refresh()
    source, destination = VirtualDevice("Six input", "5.1"), VirtualDevice("Six output", "5.1")
    try:
        for config in (source, destination):
            backend.create_virtual_device(config)
        route = backend.create_route(
            "source:" + source.device_id.removeprefix("sink:") + ".monitor",
            destination.device_id,
            channel_map=[{"source": i, "destination": (i + 1) % 6, "gain": 1} for i in range(6)],
        )
        assert route.status == "connected", route.error
        verify_mapping(source, destination, expected=[[(i - 1) % 6] for i in range(6)])
        backend.set_route_channel_map(
            route.id,
            [
                {"source": 0, "destination": 0, "gain": 1},
                {"source": 1, "destination": 0, "gain": 1},
            ],
        )
        verify_mapping(source, destination, expected=[[0, 1], [], [], [], [], []])
    finally:
        backend.cleanup_owned()


def test_partial_matrix_creation_rolls_back(monkeypatch):
    backend = PipeWireBackend(owner="test_" + uuid4().hex)
    backend.refresh()
    source, destination = VirtualDevice("Failure source"), VirtualDevice("Failure output")
    try:
        for config in (source, destination):
            backend.create_virtual_device(config)
        original = backend._load
        attempts = []

        def fail_second(module, *args):
            if module == "module-loopback":
                attempts.append(module)
                if len(attempts) == 2:
                    raise BackendError("Injected loopback creation failure")
            return original(module, *args)

        monkeypatch.setattr(backend, "_load", fail_second)
        route = backend.create_route(
            "source:" + source.device_id.removeprefix("sink:") + ".monitor",
            destination.device_id,
            channel_map=[{"source": 0, "destination": i, "gain": 1} for i in (0, 1)],
        )
        assert route.status == "error" and "Injected" in route.error
        assert not backend._find("matrix", route.id)
    finally:
        backend.cleanup_owned()


@pytest.mark.parametrize("name", ["A 'quoted' cable", 'A "quoted" cable', "A 'quoted' \"cable\" \\ test"])
def test_pulse_virtual_name_preserved(name):
    backend = PipeWireBackend(owner="test_" + uuid4().hex)
    backend.refresh()
    config = VirtualDevice(name)
    try:
        backend.create_virtual_device(config)
        assert backend.get_device(config.device_id).name == name
    finally:
        backend.cleanup_owned()


def test_matrix_gui_applies_six_channels_without_hidden_route_selection(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from test_gui import shutdown, wait

    from a2router.controller import Controller
    from a2router.ui import MainWindow

    app = QApplication.instance() or QApplication([])
    backend = PipeWireBackend(owner="test_" + uuid4().hex)
    backend.refresh()
    source, destination = VirtualDevice("GUI six input", "5.1"), VirtualDevice("GUI six output", "5.1")
    window = None
    try:
        for config in (source, destination):
            backend.create_virtual_device(config)
        source_id = "source:" + source.device_id.removeprefix("sink:") + ".monitor"
        route = backend.create_route(source_id, destination.device_id)
        window = MainWindow(Controller(backend))
        wait(app, window)
        window.show()
        matrix = window.studio.matrix
        matrix.source_selector.setCurrentIndex(matrix.source_selector.findData(source_id))
        matrix.destination_selector.setCurrentIndex(
            matrix.destination_selector.findData(destination.device_id)
        )
        window.route_tree.clearSelection()
        assert matrix.grid.isEnabled()
        assert matrix.grid.rowCount() == matrix.grid.columnCount() == 6
        assert not matrix.gain.isEnabled()
        matrix.mapping_buttons[0].click()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
        matrix.mapping_buttons[-1].click()
        wait(app, window)
        assert route.status == "connected", route.error
        assert len(route.channel_map) == 6 and len(route.resource_ids) == 2
        if executable := os.environ.get("A2ROUTER_FROZEN_APP"):
            import json
            import subprocess

            report = tmp_path / "frozen-pulse.json"
            subprocess.run([executable, "--self-test", str(report)], check=True, timeout=35)
            observed = json.loads(report.read_text())
            assert observed["frozen"] and not observed["simulated"]
            assert observed["backend"]["capabilities"]["channel_routing"]
    finally:
        if window:
            shutdown(app, window)
        backend.cleanup_owned()
