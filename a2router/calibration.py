"""Offline acoustic analysis. Playback/capture is always native, never a Python callback."""

import math
from datetime import datetime, timezone

import numpy as np

from a2router.models import BackendError

DURATION = 0.18


def chirp(rate):
    t = np.arange(round(rate * DURATION), dtype=np.float64) / rate
    return np.sin(2 * np.pi * (800 * t + 0.5 * 3000 / DURATION * t**2)) * (
        0.5 - 0.5 * np.cos(2 * np.pi * t / DURATION)
    )


def analyze(recording):
    """Matched-filter arrival relative to the native monotonic software-start epoch.

    Reports the strongest unambiguous chirp arrival, not a separated measurement
    of distance/driver/transport delay. Capture timestamp validity is checked natively.
    """
    try:
        rate = recording["sample_rate"]
        if type(rate) is not int or not 8000 <= rate <= 192000:
            raise ValueError("Unsupported microphone rate")
        first, signal = recording["capture_start_100ns"], recording["signal_time_100ns"]
        if type(first) is not int or type(signal) is not int or min(first, signal) < 0:
            raise ValueError("Invalid monotonic timestamps")
        samples = np.asarray(recording["samples"], dtype=np.float64)
        if samples.ndim != 1 or not rate // 2 <= len(samples) <= rate * 4 or not np.isfinite(samples).all():
            raise ValueError("Invalid microphone recording")
        if np.max(np.abs(samples)) >= 0.98:
            raise ValueError("Microphone clipping; reduce input gain and retry")
        noise = samples[: max(1, rate // 5)]
        samples = samples - np.mean(noise)
        noise_rms = float(np.sqrt(np.mean((noise - np.mean(noise)) ** 2)))
        template = chirp(rate)
        expected = (signal - first) * rate / 10_000_000
        low = max(0, math.floor(expected - 0.03 * rate))
        high = min(len(samples) - len(template), math.ceil(expected + 2 * rate))
        if high <= low:
            raise ValueError("Recording does not span the expected signal")
        size = 1 << (len(samples) + len(template) - 1).bit_length()
        correlation = np.fft.irfft(np.fft.rfft(samples, size) * np.conj(np.fft.rfft(template, size)), size)
        energy = np.r_[0.0, np.cumsum(samples * samples)]
        window_energy = np.maximum(energy[len(template) :] - energy[: -len(template)], 1e-24)
        normalized = np.abs(correlation[: len(window_energy)]) / np.sqrt(
            window_energy * np.dot(template, template)
        )
        selected = normalized[low : high + 1]
        peak = low + int(np.argmax(selected))
        confidence = min(1.0, float(normalized[peak]))
        mask = np.ones(len(selected), dtype=bool)
        exclusion = round(0.025 * rate)
        mask[max(0, peak - low - exclusion) : min(len(mask), peak - low + exclusion + 1)] = False
        competitor = float(np.max(selected[mask])) if np.any(mask) else 0.0
        signal_rms = math.sqrt(float(window_energy[peak]) / len(template))
        snr = min(120.0, 10 * math.log10(max(signal_rms**2 - noise_rms**2, 1e-24) / max(noise_rms**2, 1e-24)))
        if confidence < 0.25 or snr < 6:
            raise ValueError("Chirp is too weak/noisy; check microphone position and test level")
        if competitor > confidence / 1.12:
            raise ValueError("Ambiguous arrivals/reflections; reposition the microphone and retry")
        return {
            "arrival_ms": (peak - expected) * 1000 / rate,
            "confidence": confidence,
            "snr_db": max(-120.0, snr),
            "sample_rate": rate,
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise BackendError(f"Calibration analysis: {exc}") from exc


def summarize(passes, requested):
    if len(passes) < max(1, (requested + 1) // 2):
        raise BackendError("Too few usable measurement passes")
    arrival = np.array([p["arrival_ms"] for p in passes])
    median = float(np.median(arrival))
    mad = float(np.median(np.abs(arrival - median)))
    kept = [p for p in passes if abs(p["arrival_ms"] - median) <= max(1.5, 3 * mad)]
    if len(kept) < max(1, (requested + 1) // 2):
        raise BackendError("Measurement passes disagree")
    spread = max(p["arrival_ms"] for p in kept) - min(p["arrival_ms"] for p in kept)
    if spread > 10:
        raise BackendError("Output latency is unstable by more than 10 ms; no compensation recommended")
    confidence = float(np.median([p["confidence"] for p in kept])) * math.exp(-spread / 10)
    if requested == 1:
        confidence = min(confidence, 0.75)
    return {
        "arrival_ms": float(np.median([p["arrival_ms"] for p in kept])),
        "confidence": confidence,
        "snr_db": float(np.median([p["snr_db"] for p in kept])),
        "spread_ms": spread,
        "passes_used": len(kept),
    }


def check_request(backend, microphone_id, outputs, reference_id, passes, level_db, channel):
    if not backend.capabilities().get("calibration"):
        raise BackendError("Native microphone calibration is unavailable; rebuild the Windows DLL")
    if not isinstance(outputs, list) or not 2 <= len(outputs) <= 16 or len(set(outputs)) != len(outputs):
        raise BackendError("Choose two to sixteen distinct physical outputs")
    if reference_id not in outputs or type(passes) is not int or not 1 <= passes <= 5:
        raise BackendError("Select a reference output and one to five passes")
    if type(level_db) not in (int, float) or not -50 <= level_db <= -20:
        raise BackendError("Test level must be between −50 and −20 dBFS")
    mic = backend.get_device(microphone_id)
    if mic.kind != "input" or mic.monitor_of or mic.virtual is True:
        raise BackendError("Select a physical microphone, not an output loopback or virtual cable")
    if type(channel) is not int or not mic.channels or not 0 <= channel < mic.channels:
        raise BackendError("Select a reported microphone channel")
    for ident in [microphone_id, *outputs]:
        device = backend.get_device(ident)
        if ident in outputs and (device.kind != "output" or device.virtual is True):
            raise BackendError("Acoustic calibration requires physical playback outputs")
        if device.properties.get("controls", {}).get("muted"):
            raise BackendError(f"Unmute {device.name} before measuring")


def measure(backend, microphone_id, outputs, reference_id, passes, level_db, channel, progress):
    check_request(backend, microphone_id, outputs, reference_id, passes, level_db, channel)
    backend.reset_calibration()
    measured, rates = [], set()
    total = len(outputs) * passes
    for output_index, ident in enumerate(outputs):
        valid, errors = [], []
        for attempt in range(passes):
            if backend.calibration_cancelled():
                raise BackendError("Calibration cancelled")
            progress(
                output_index * passes + attempt,
                total,
                f"{backend.get_device(ident).name}: pass {attempt + 1}/{passes}",
            )
            try:
                recording = backend.record_calibration(microphone_id, ident, 10 ** (level_db / 20), channel)
                result = analyze(recording)
                valid.append(result)
                rates.add(result["sample_rate"])
            except BackendError as exc:
                errors.append(str(exc))
                if backend.calibration_cancelled():
                    raise BackendError("Calibration cancelled") from exc
        try:
            measured.append({"device_id": ident, **summarize(valid, passes)})
        except BackendError as exc:
            details = "; ".join(dict.fromkeys(errors))
            raise BackendError(f"{backend.get_device(ident).name}: {exc}. {details}".rstrip(". ")) from exc
    if len(rates) != 1:
        raise BackendError("Microphone rate changed during calibration; retry")
    reference = next(p["arrival_ms"] for p in measured if p["device_id"] == reference_id)
    slowest = max(p["arrival_ms"] for p in measured)
    for item in measured:
        item.update(relative_ms=item["arrival_ms"] - reference, compensation_ms=slowest - item["arrival_ms"])
    progress(total, total, "Measurement complete; review before applying")
    return {
        "version": 1,
        "method": "acoustic-chirp",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "microphone_id": microphone_id,
        "microphone_channel": channel,
        "reference_output_id": reference_id,
        "sample_rate": rates.pop(),
        "passes": passes,
        "outputs": measured,
    }


def validate_result(data):
    try:
        if not isinstance(data, dict) or set(data) != {
            "version",
            "method",
            "timestamp",
            "microphone_id",
            "microphone_channel",
            "reference_output_id",
            "sample_rate",
            "passes",
            "outputs",
        }:
            raise ValueError("Invalid calibration metadata")
        if type(data["version"]) is not int or data["version"] != 1 or data["method"] != "acoustic-chirp":
            raise ValueError("Unsupported calibration version/method")
        if (
            not isinstance(data["timestamp"], str)
            or len(data["timestamp"]) > 64
            or datetime.fromisoformat(data["timestamp"]).tzinfo is None
        ):
            raise ValueError("Calibration timestamp must include timezone")
        for key in ("microphone_id", "reference_output_id"):
            if not isinstance(data[key], str) or not 0 < len(data[key]) <= 2048:
                raise ValueError("Invalid calibration device ID")
        for key, low, high in [
            ("sample_rate", 8000, 192000),
            ("passes", 1, 5),
            ("microphone_channel", 0, 63),
        ]:
            if type(data[key]) is not int or not low <= data[key] <= high:
                raise ValueError("Invalid calibration setting")
        if not isinstance(data["outputs"], list) or not 2 <= len(data["outputs"]) <= 16:
            raise ValueError("Invalid calibration outputs")
        seen = set()
        for row in data["outputs"]:
            if not isinstance(row, dict) or set(row) != {
                "device_id",
                "arrival_ms",
                "relative_ms",
                "compensation_ms",
                "confidence",
                "snr_db",
                "spread_ms",
                "passes_used",
            }:
                raise ValueError("Invalid calibration output fields")
            ident = row["device_id"]
            if not isinstance(ident, str) or not 0 < len(ident) <= 2048 or ident in seen:
                raise ValueError("Invalid/duplicate calibration output")
            seen.add(ident)
            for key, low, high in [
                ("arrival_ms", -30, 2000),
                ("relative_ms", -2030, 2030),
                ("compensation_ms", 0, 2030),
                ("confidence", 0, 1),
                ("snr_db", -120, 120),
                ("spread_ms", 0, 10),
            ]:
                value = row[key]
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError("Invalid calibration measurement")
            if type(row["passes_used"]) is not int or not 1 <= row["passes_used"] <= data["passes"]:
                raise ValueError("Invalid pass count")
        if data["reference_output_id"] not in seen:
            raise ValueError("Reference is missing from calibration")
        return data
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise BackendError(f"Invalid calibration: {exc}") from exc
