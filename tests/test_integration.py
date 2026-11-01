"""Opt-in real server tests. All test routes terminate at owned silent virtual sinks."""

import os
import time
from uuid import uuid4

import pytest

from a2router.backends.linux_pipewire import PipeWireBackend
from a2router.controller import Controller
from a2router.models import LAYOUTS, BackendError, VirtualDevice

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
            name = "a2router 'test' \"" + layout + '"'
            if backend._legacy_property_parser():
                # The old parser cannot unescape mixed quote types. Verify
                # rejection before allocation, then test each supported type.
                before = backend._modules()
                with pytest.raises(BackendError, match="simpler name"):
                    backend.create_virtual_device(VirtualDevice(name, layout))
                assert backend._modules() == before
                name = ("a2router 'test' " if layout == "mono" else 'a2router "test" ') + layout
            config = VirtualDevice(name, layout)
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
        backend.set_device_volume(output_b.device_id, 0.3333)
        assert backend.get_device(output_b.device_id).properties["controls"]["volume"] == pytest.approx(
            0.3333, abs=1 / 65536
        )
        backend.set_device_mute(output_b.device_id, True)
        assert backend.get_device(output_b.device_id).properties["controls"]["muted"] is True
        backend.set_device_mute(output_b.device_id, False)
        backend.set_device_volume(output_b.device_id, 1.0)
        routes = [
            backend.create_route(monitor(s), d.device_id)
            for s, d in ((stereo, output_a), (stereo, output_b), (source_b, output_a))
        ]
        for r in routes:
            assert r.status == "connected", r.error
            assert len(r.resource_ids) == 1
        if backend.capabilities().get("route_delay"):
            other_resources = [list(route.resource_ids) for route in routes[1:]]
            with pytest.raises(BackendError, match="restarting"):
                backend.set_route_delay(routes[0].id, 20)
            backend.set_route_delay(routes[0].id, 20, allow_restart=True)
            assert routes[0].delay_ms == 20 and routes[0].status == "connected"
            assert [route.resource_ids for route in routes[1:]] == other_resources
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
        if backend.capabilities().get("channel_routing"):
            backend.set_route_channel_map(
                routes[1].id,
                [
                    {"source": 0, "destination": 0, "gain": 1},
                    {"source": 1, "destination": 1, "gain": 1},
                ],
            )
            assert routes[1].status == "connected", routes[1].error
            assert all(resource.startswith("link:") for resource in routes[1].resource_ids)
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


def test_application_copy_isolation_fanout_live_mapping_and_reconnect(tmp_path):
    import shutil
    import subprocess

    import numpy as np

    backend = PipeWireBackend(owner="test_" + uuid4().hex)
    backend.refresh()
    if not backend.capabilities().get("applications"):
        pytest.skip("Native application copies require pw-dump and pw-link")
    definitions = [
        VirtualDevice(name) for name in ("Original apps", "Application copy A", "Application copy B")
    ]
    children = []
    rate = 48000
    target_file, other_file = tmp_path / "target.pcm", tmp_path / "other.pcm"
    timeline = np.arange(rate * 24, dtype=np.float32) / rate
    np.column_stack(
        (0.1 * np.sin(2 * np.pi * 431 * timeline), 0.1 * np.sin(2 * np.pi * 997 * timeline))
    ).astype("<f4").tofile(target_file)
    np.column_stack((0.1 * np.sin(2 * np.pi * 1699 * timeline),) * 2).astype("<f4").tofile(other_file)
    target_binary = shutil.which("pacat")
    other_binary = tmp_path / "different-player"
    shutil.copy2(target_binary, other_binary)
    other_binary.chmod(0o755)

    def play(binary, pcm, name):
        with pcm.open("rb") as stream:
            process = subprocess.Popen(
                [
                    str(binary),
                    "--playback",
                    "--raw",
                    "--format=float32le",
                    "--rate=48000",
                    "--channels=2",
                    "--latency-msec=40",
                    "--device=" + definitions[0].device_id[5:],
                    "--property=application.name=" + name,
                ],
                stdin=stream,
            )
        children.append(process)
        return process

    def wait_routes(ident=None):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            backend.refresh()
            names = [d.name for d in backend.list_devices() if d.properties.get("application_capture")]
            if ident is None and all(
                any(label in name for name in names) for label in ("target player", "unrelated player")
            ):
                return
            if ident is not None and all(r.status == "connected" for r in backend.list_routes()):
                return
            time.sleep(0.05)
        raise AssertionError(backend.diagnostics())

    def amplitudes(config):
        path = tmp_path / "captured.pcm"
        with path.open("wb") as recording:
            process = subprocess.Popen(
                [
                    "parec",
                    "--raw",
                    "--format=float32le",
                    "--rate=48000",
                    "--channels=2",
                    "--latency-msec=20",
                    "--device=" + config.device_id[5:] + ".monitor",
                ],
                stdout=recording,
            )
            try:
                time.sleep(1.3)
            finally:
                process.terminate()
                process.wait(timeout=5)
        samples = np.fromfile(path, dtype="<f4").reshape(-1, 2)[rate // 4 :]
        assert len(samples) > rate // 4
        t = np.arange(len(samples)) / rate
        return {
            frequency: np.abs(np.mean(samples * np.exp(-2j * np.pi * frequency * t)[:, None], axis=0)) * 2
            for frequency in (431, 997, 1699)
        }

    try:
        for config in definitions:
            backend.create_virtual_device(config)
        target = play(target_binary, target_file, "A2 target player")
        play(other_binary, other_file, "A2 unrelated player")
        wait_routes()
        application = next(
            d
            for d in backend.list_devices()
            if d.properties.get("application_capture") and "target player" in d.name
        )
        original_sink = next(
            s["sink"]
            for s in backend.sink_inputs
            if s.get("properties", {}).get("application.name") == "A2 target player"
        )
        routes = [backend.create_route(application.id, d.device_id) for d in definitions[1:]]
        assert all(r.status == "connected" for r in routes), backend.diagnostics()
        unchanged_links = [list(r.resource_ids) for r in routes]
        with pytest.raises(BackendError, match="do not support extra delay|Latency targets require PipeWire"):
            backend.set_route_delay(routes[0].id, 20, allow_restart=True)
        assert [r.resource_ids for r in routes] == unchanged_links
        original_audio = amplitudes(definitions[0])
        assert min(original_audio[1699]) > 0.04  # The unrelated app is actually producing audio.
        initial = amplitudes(definitions[1])
        assert initial[431][0] > 0.04 and initial[997][1] > 0.04
        assert max(initial[1699]) < 0.005  # Unrelated software was not copied.
        other_links = list(routes[1].resource_ids)
        backend.set_route_channel_map(
            routes[0].id,
            [
                {"source": 0, "destination": 1, "gain": 1},
                {"source": 1, "destination": 0, "gain": 1},
            ],
        )
        swapped = amplitudes(definitions[1])
        assert swapped[997][0] > 0.04 and swapped[431][1] > 0.04
        assert routes[1].resource_ids == other_links and target.poll() is None
        unchanged = amplitudes(definitions[2])
        assert unchanged[431][0] > 0.04 and unchanged[997][1] > 0.04
        backend.refresh()
        assert (
            next(
                s["sink"]
                for s in backend.sink_inputs
                if s.get("properties", {}).get("application.name") == "A2 target player"
            )
            == original_sink
        )
        if os.environ.get("A2ROUTER_FROZEN_APP"):
            import json

            report_path = tmp_path / "frozen-app-discovery.json"
            environment = {
                **os.environ,
                "XDG_CONFIG_HOME": str(tmp_path / "frozen-settings"),
                "QT_QPA_PLATFORM": "offscreen",
            }
            subprocess.run(
                [os.environ["A2ROUTER_FROZEN_APP"], "--self-test", str(report_path)],
                env=environment,
                cwd=tmp_path,
                check=True,
                timeout=45,
            )
            report = json.loads(report_path.read_text())
            assert not report["simulated"] and report["backend"]["capabilities"]["applications"]
            assert all(report["checks"].values())
        saved = Controller(backend).snapshot()
        replacement = PipeWireBackend(owner=backend.owner)
        assert Controller(replacement).restore(saved) == []
        assert all(r.status == "connected" for r in replacement.list_routes())
        target.terminate()
        target.wait(timeout=5)
        backend.refresh()
        assert all(r.status == "pending" for r in routes)
        play(target_binary, target_file, "A2 target player")
        wait_routes(application.id)
        assert all(r.status == "connected" for r in routes)
        assert len(backend.graph.owned()) == 4
        for route in routes:
            backend.remove_route(route.id)
        assert not backend.graph.owned()
        assert children[-1].poll() is None  # Removing copies preserves original playback.
    finally:
        for process in reversed(children):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        backend.cleanup_owned()
        if backend.graph_available:
            assert not backend.graph.owned()


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
