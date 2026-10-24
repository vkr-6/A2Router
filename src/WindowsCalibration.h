#pragma once
// Finite, user-initiated WASAPI measurement. No Qt/Python sample callbacks.
#include "WindowsEndpointControl.h"
#include "CalibrationSignal.h"
#include <atomic>
#include <chrono>
#include <memory>
#include <sstream>
#include <thread>

namespace a2r {
inline std::atomic<bool> calibrationCancelled{false};
inline void calibrationCheck(HRESULT hr, const char* operation) {
    if (FAILED(hr)) {
        std::ostringstream message;
        message << operation << " failed (HRESULT 0x" << std::hex << static_cast<unsigned long>(hr)
                << "). Check device availability, microphone permission and shared-mode access.";
        throw std::runtime_error(message.str());
    }
}
inline mux::PcmEncoding calibrationEncoding(const WAVEFORMATEX* f) {
    mux::PcmEncoding result{f->nChannels, f->wBitsPerSample, f->wBitsPerSample, f->wFormatTag == WAVE_FORMAT_IEEE_FLOAT};
    if (f->wFormatTag == WAVE_FORMAT_EXTENSIBLE && f->cbSize >= 22) {
        const auto* ext = reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(f);
        result.valid_bits = ext->Samples.wValidBitsPerSample ? ext->Samples.wValidBitsPerSample : f->wBitsPerSample;
        result.floating = ext->SubFormat.Data1 == WAVE_FORMAT_IEEE_FLOAT;
        if (ext->SubFormat.Data2 != 0 || ext->SubFormat.Data3 != 0x10 ||
            (ext->SubFormat.Data1 != WAVE_FORMAT_PCM && !result.floating))
            throw std::runtime_error("Unsupported calibration PCM subtype");
    } else if (f->wFormatTag != WAVE_FORMAT_PCM && f->wFormatTag != WAVE_FORMAT_IEEE_FLOAT) {
        throw std::runtime_error("Calibration requires PCM or float32 shared-mode audio");
    }
    if (!result.supported() || f->nBlockAlign != result.channels * result.bits / 8 ||
        f->nSamplesPerSec < 8000 || f->nSamplesPerSec > 192000)
        throw std::runtime_error("Unsupported calibration mix format");
    return result;
}
struct CalibrationRecording {
    unsigned rate = 0;
    uint64_t firstQpc = 0;
    uint64_t signalQpc = 0;
    std::vector<float> samples;
};
struct CalibrationClients {
    ComPtr<IAudioClient> capture, render;
    bool captureStarted = false, renderStarted = false;
    ~CalibrationClients() {
        if (renderStarted) render->Stop();
        if (captureStarted) capture->Stop();
    }
};
inline uint64_t calibrationQpc() {
    LARGE_INTEGER ticks{}, frequency{};
    QueryPerformanceCounter(&ticks); QueryPerformanceFrequency(&frequency);
    return static_cast<uint64_t>(static_cast<long double>(ticks.QuadPart) * 10000000 / frequency.QuadPart);
}
inline CalibrationRecording recordCalibration(const wchar_t* micId, const wchar_t* outputId,
                                               double amplitude, unsigned microphoneChannel) {
    if (!micId || !outputId || !*micId || !*outputId || !std::isfinite(amplitude) || amplitude < 0.003 || amplitude > 0.100001)
        throw std::runtime_error("Invalid microphone, output or test level");
    amplitude = std::min(amplitude, 0.1); // c_float rounding at the -20 dBFS UI ceiling.
    auto mic = endpoint(micId), output = endpoint(outputId);
    if (!mic || !output) throw std::runtime_error("Calibration device is unavailable");
    ComPtr<IMMEndpoint> micFlow, outputFlow;
    EDataFlow mflow = eAll, oflow = eAll;
    calibrationCheck(mic.As(&micFlow), "Microphone classification");
    calibrationCheck(output.As(&outputFlow), "Output classification");
    calibrationCheck(micFlow->GetDataFlow(&mflow), "Microphone classification");
    calibrationCheck(outputFlow->GetDataFlow(&oflow), "Output classification");
    if (mflow != eCapture || oflow != eRender) throw std::runtime_error("Select a capture microphone and playback output");
    CalibrationClients clients;
    calibrationCheck(mic->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
        reinterpret_cast<void**>(clients.capture.GetAddressOf())), "Microphone activation");
    calibrationCheck(output->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
        reinterpret_cast<void**>(clients.render.GetAddressOf())), "Output activation");
    WAVEFORMATEX *micRaw = nullptr, *outputRaw = nullptr;
    calibrationCheck(clients.capture->GetMixFormat(&micRaw), "Microphone mix format");
    std::unique_ptr<WAVEFORMATEX, decltype(&CoTaskMemFree)> micFormat(micRaw, &CoTaskMemFree);
    calibrationCheck(clients.render->GetMixFormat(&outputRaw), "Output mix format");
    std::unique_ptr<WAVEFORMATEX, decltype(&CoTaskMemFree)> outputFormat(outputRaw, &CoTaskMemFree);
    const auto inputEncoding = calibrationEncoding(micRaw), outputEncoding = calibrationEncoding(outputRaw);
    if (microphoneChannel >= inputEncoding.channels) throw std::runtime_error("Microphone channel is unavailable");
    // A separate audio session keeps the test distinct from managed program streams.
    const GUID testSession = {0x19c45893, 0x43e6, 0x4870, {0x9e, 0x13, 0x30, 0xdd, 0x28, 0x45, 0x75, 0x82}};
    calibrationCheck(clients.capture->Initialize(AUDCLNT_SHAREMODE_SHARED, 0, 1000000, 0, micRaw, &testSession), "Microphone initialization");
    calibrationCheck(clients.render->Initialize(AUDCLNT_SHAREMODE_SHARED, 0, 1000000, 0, outputRaw, &testSession), "Output initialization");
    ComPtr<IAudioCaptureClient> capture;
    ComPtr<IAudioRenderClient> render;
    calibrationCheck(clients.capture->GetService(IID_PPV_ARGS(&capture)), "Microphone capture service");
    calibrationCheck(clients.render->GetService(IID_PPV_ARGS(&render)), "Output render service");
    UINT32 capacity = 0;
    calibrationCheck(clients.render->GetBufferSize(&capacity), "Output buffer size");
    BYTE* initial = nullptr;
    calibrationCheck(render->GetBuffer(capacity, &initial), "Output prefill");
    for (UINT32 i = 0; i < capacity; ++i) {
        const double sample = amplitude * calibrationChirp(i / double(outputRaw->nSamplesPerSec) - 0.45);
        for (unsigned channel = 0; channel < outputEncoding.channels; ++channel)
            writeCalibrationSample(initial + size_t(i) * outputRaw->nBlockAlign + channel * outputEncoding.bits / 8,
                outputEncoding, channel == 0 ? sample : 0.0);
    }
    calibrationCheck(render->ReleaseBuffer(capacity, 0), "Output prefill release");
    CalibrationRecording recording;
    recording.rate = micRaw->nSamplesPerSec;
    recording.samples.resize(static_cast<size_t>(recording.rate) * 4, 0);
    size_t recorded = 0;
    bool ambientChecked = false;
    uint64_t rendered = capacity;
    calibrationCheck(clients.capture->Start(), "Microphone start"); clients.captureStarted = true;
    const auto start = calibrationQpc();
    calibrationCheck(clients.render->Start(), "Output start"); clients.renderStarted = true;
    // Reference is a common monotonic software-start epoch, not a fabricated
    // hardware presentation timestamp. Relative measurements retain startup jitter.
    recording.signalQpc = start + 4500000;
    while (calibrationQpc() - start < 32000000) {
        if (calibrationCancelled.load(std::memory_order_relaxed)) throw std::runtime_error("Calibration cancelled");
        UINT32 frames = 0;
        calibrationCheck(capture->GetNextPacketSize(&frames), "Microphone packet query");
        while (frames) {
            BYTE* data = nullptr; DWORD flags = 0; UINT64 position = 0, qpc = 0;
            calibrationCheck(capture->GetBuffer(&data, &frames, &flags, &position, &qpc), "Microphone packet");
            const bool invalid = (flags & AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR) || !qpc ||
                (!data && !(flags & AUDCLNT_BUFFERFLAGS_SILENT)) ||
                (recording.firstQpc && (flags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY));
            if (!recording.firstQpc) recording.firstQpc = qpc;
            const int64_t offset = qpc >= recording.firstQpc
                ? static_cast<int64_t>(std::llround((qpc - recording.firstQpc) * double(recording.rate) / 10000000)) : -1;
            const bool bounds = offset >= 0 && static_cast<uint64_t>(offset) + frames <= recording.samples.size();
            if (!invalid && bounds) {
                for (UINT32 i = 0; i < frames; ++i) {
                    recording.samples[static_cast<size_t>(offset) + i] = flags & AUDCLNT_BUFFERFLAGS_SILENT ? 0.0f :
                        static_cast<float>(inputEncoding.read(data + size_t(i) * micRaw->nBlockAlign + microphoneChannel * inputEncoding.bits / 8));
                }
                recorded = std::max(recorded, static_cast<size_t>(offset) + frames);
            }
            calibrationCheck(capture->ReleaseBuffer(frames), "Microphone packet release");
            if (invalid || !bounds) throw std::runtime_error("Unreliable microphone timestamps or capture discontinuity; retry measurement");
            calibrationCheck(capture->GetNextPacketSize(&frames), "Microphone packet query");
        }
        if (!ambientChecked && calibrationQpc() - start > 2500000) {
            const auto count = std::min(recorded, size_t(recording.rate) / 5);
            double energy = 0;
            for (size_t i = 0; i < count; ++i) energy += recording.samples[i] * double(recording.samples[i]);
            if (!count || energy / count < 1e-18)
                throw std::runtime_error("No ambient microphone signal. Check mute, channel selection and microphone permission");
            if (energy / count > 0.09)
                throw std::runtime_error("Microphone input is too loud for calibration. Reduce input gain or ambient noise");
            ambientChecked = true;
        }
        UINT32 padding = 0;
        calibrationCheck(clients.render->GetCurrentPadding(&padding), "Output padding");
        if (padding > capacity) throw std::runtime_error("Invalid output buffer state");
        if (!padding && rendered > capacity && calibrationQpc() - start > 1000000)
            throw std::runtime_error("Calibration output underrun; close busy applications and retry");
        const UINT32 available = capacity - padding;
        if (available) {
            BYTE* data = nullptr;
            calibrationCheck(render->GetBuffer(available, &data), "Output buffer");
            for (UINT32 i = 0; i < available; ++i) {
                const double sample = amplitude * calibrationChirp((rendered + i) / double(outputRaw->nSamplesPerSec) - 0.45);
                for (unsigned channel = 0; channel < outputEncoding.channels; ++channel)
                    writeCalibrationSample(data + size_t(i) * outputRaw->nBlockAlign + channel * outputEncoding.bits / 8,
                        outputEncoding, channel == 0 ? sample : 0.0);
            }
            calibrationCheck(render->ReleaseBuffer(available, 0), "Output buffer release");
            rendered += available;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    if (!recorded || !recording.firstQpc) throw std::runtime_error("The microphone returned no usable samples");
    recording.samples.resize(recorded);
    return recording;
}
}
