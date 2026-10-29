"""Synthetic offline analysis and simulated capture tests, never hardware claims."""

import copy
import json
from dataclasses import asdict

import numpy as np
import pytest

from a2router import storage
from a2router.backends.mock import MockBackend
from a2router.calibration import analyze, chirp, summarize, validate_result
from a2router.controller import Controller
from a2router.models import BackendError


def recording(delay_ms, rate=16000, noise=0.0001, echo=False):
    samples = np.random.default_rng(42).normal(0, noise, rate * 3)
    reference = round(0.45 * rate)
    signal = chirp(rate) * 0.03
    start = reference + round(delay_ms * rate / 1000)
    samples[start : start + len(signal)] += signal
    if echo:
        samples[start + rate // 3 : start + rate // 3 + len(signal)] += signal
    return {
        "sample_rate": rate,
        "capture_start_100ns": 1_000_000_000,
        "signal_time_100ns": 1_004_500_000,
        "samples": samples.tolist(),
    }


@pytest.mark.parametrize("rate", [16000, 44100, 48000])
@pytest.mark.parametrize("delay", [5, 42.5, 390])
def test_known_chirp_arrival(rate, delay):
    result = analyze(recording(delay, rate))
    assert result["arrival_ms"] == pytest.approx(delay, abs=1000 / rate)
    assert result["confidence"] > 0.95 and result["snr_db"] > 20


def test_noise_clipping_and_ambiguous_reflections_are_rejected():
    for data in [recording(20, noise=0.15), recording(20, echo=True)]:
        with pytest.raises(BackendError):
            analyze(data)
    data = recording(20)
    data["samples"][200] = 1
    with pytest.raises(BackendError, match="clipping"):
        analyze(data)
    data = recording(20)
    data["samples"][100] = float("nan")
    with pytest.raises(BackendError, match="Invalid microphone"):
        analyze(data)


def test_multipass_outlier_and_variable_latency():
    passes = [{"arrival_ms": v, "confidence": 0.95, "snr_db": 30} for v in [12, 12.5, 110]]
    result = summarize(passes, 3)
    assert result["passes_used"] == 2 and result["arrival_ms"] == 12.25
    with pytest.raises(BackendError, match="unstable"):
        summarize([{"arrival_ms": v, "confidence": 0.95, "snr_db": 30} for v in [10, 30, 50]], 3)


class CaptureBackend(MockBackend):
    def __init__(self):
        super().__init__()
        self.cancelled = False
        self.fail_capture = False
        self.fail_delay = None
        self.capture_calls = []
        self.routes_during_capture = []

    def capabilities(self):
        return {**super().capabilities(), "calibration": True, "route_delay": True, "live_route_delay": True}

    def reset_calibration(self):
        self.cancelled = False

    def calibration_cancelled(self):
        return self.cancelled

    def cancel_calibration(self):
        self.cancelled = True

    def record_calibration(self, mic, output, level, channel):
        self.capture_calls.append((mic, output, level, channel))
        self.routes_during_capture.append(set(self.resources))
        if self.fail_capture:
            raise BackendError("Microphone permission denied")
        return recording(12 if output == "speakers" else 75)

    def set_route_delay(self, ident, delay, **kwargs):
        if self.fail_delay == (ident, delay):
            raise BackendError("delay rejected")
        self.routes[ident].delay_ms = delay


def measure_backend(backend, progress=lambda *args: None):
    controller = Controller(backend)
    controller.measure_calibration("mic", ["speakers", "headphones"], "speakers", 3, -36, 0, progress)
    return controller


def test_real_capture_boundary_and_review_first_restore(tmp_path):
    backend = CaptureBackend()
    first = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    second = backend.create_route("mic", "headphones", enabled=False, monitoring_confirmed=True)
    controller = measure_backend(backend)
    assert backend.resources == {first.id} and not second.enabled
    assert all(not resources for resources in backend.routes_during_capture)
    assert len(backend.capture_calls) == 6
    assert first.delay_ms == second.delay_ms == 0  # Measurement never applies compensation automatically.
    outputs = {r["device_id"]: r for r in controller.calibration["outputs"]}
    assert outputs["speakers"]["compensation_ms"] == pytest.approx(63)
    assert outputs["headphones"]["compensation_ms"] == 0
    path = tmp_path / "profile.json"
    controller.save(path)
    assert storage.load(path)["calibration"] == controller.calibration
    controller.apply_calibration({"speakers": 63, "headphones": 0})
    assert first.delay_ms == 63 and second.delay_ms == 0


def test_capture_failure_and_cancellation_restore_enabled_state():
    backend = CaptureBackend()
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    backend.fail_capture = True
    with pytest.raises(BackendError, match="permission"):
        measure_backend(backend)
    assert backend.resources == {route.id} and route.enabled
    backend.fail_capture = False

    def cancel(*args):
        backend.cancel_calibration()

    with pytest.raises(BackendError, match="cancelled"):
        measure_backend(backend, cancel)
    assert backend.resources == {route.id} and route.enabled


def test_apply_failure_rolls_back_and_invalid_metadata_cannot_replace_profile(tmp_path):
    backend = CaptureBackend()
    first = backend.create_route("mic", "speakers", monitoring_confirmed=True, delay_ms=3)
    second = backend.create_route("mic", "headphones", monitoring_confirmed=True, delay_ms=5)
    controller = measure_backend(backend)
    backend.fail_delay = (second.id, 0)
    with pytest.raises(BackendError, match="previous requests restored"):
        controller.apply_calibration({"speakers": 63, "headphones": 0})
    assert first.delay_ms == 3 and second.delay_ms == 5
    path = tmp_path / "state.json"
    controller.save(path)
    old = path.read_bytes()
    bad = copy.deepcopy(controller.snapshot())
    bad["calibration"]["outputs"][0]["confidence"] = float("nan")
    with pytest.raises(BackendError, match="Invalid calibration"):
        storage.save(path, bad)
    assert path.read_bytes() == old
    with pytest.raises(BackendError):
        validate_result({"version": 1})


def test_optional_profile_fields_migrate_old_config():
    backend = MockBackend()
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    profile = Controller(backend).snapshot()
    for row in profile["routes"]:
        row.pop("volume")
        row.pop("muted")
    new = MockBackend()
    Controller(new).restore(json.loads(json.dumps(profile)))
    assert new.routes[route.id].volume == 1 and not new.routes[route.id].muted
    assert asdict(new.routes[route.id])["source_id"] == "mic"


def test_invalid_request_never_interrupts_routing(monkeypatch):
    backend = CaptureBackend()
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    controller = Controller(backend)
    stops = []
    original = backend._disconnect

    def observed(route):
        stops.append(route.id)
        original(route)

    monkeypatch.setattr(backend, "_disconnect", observed)
    with pytest.raises(BackendError):
        controller.measure_calibration(
            "missing", ["speakers", "headphones"], "speakers", 3, -36, 0, lambda *args: None
        )
    assert not stops and backend.resources == {route.id}


def test_emergency_cancels_measurement_without_restoring_playback():
    backend = CaptureBackend()
    route = backend.create_route("mic", "speakers", monitoring_confirmed=True)
    controller = Controller(backend)
    with pytest.raises(BackendError, match="cancelled"):
        controller.measure_calibration(
            "mic",
            ["speakers", "headphones"],
            "speakers",
            3,
            -36,
            0,
            lambda *args: controller.request_emergency_stop(),
        )
    assert route.enabled and not backend.resources and not backend.transport_running
    controller.resume_routes()
    assert backend.resources == {route.id}


def test_chirp_with_silent_ambient_window_remains_measurable():
    result = analyze(recording(35, noise=0))
    assert result["arrival_ms"] == pytest.approx(35, abs=0.1)
