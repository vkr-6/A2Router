// Explicitly invoked Windows VM signal-path probe. Never changes default devices.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmdeviceapi.h>
#include <Audioclient.h>
#include <mmreg.h>
#include <wrl/client.h>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>
#include "AudioEngine.h"
using Microsoft::WRL::ComPtr;
void check(HRESULT hr, const char* message) {
    if (FAILED(hr)) throw std::runtime_error(std::string(message) + " HRESULT=" + std::to_string(static_cast<unsigned long>(hr)));
}
ComPtr<IAudioClient> openClient(const wchar_t* id) {
    ComPtr<IMMDeviceEnumerator> enumerator;
    check(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&enumerator)), "enumerator");
    ComPtr<IMMDevice> device;
    check(enumerator->GetDevice(id, &device), "explicit endpoint");
    ComPtr<IAudioClient> client;
    check(device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, reinterpret_cast<void**>(client.GetAddressOf())), "client");
    return client;
}
void tone(const wchar_t* id, double left, double right, double seconds) {
    auto client = openClient(id);
    WAVEFORMATEX format{};
    format.wFormatTag = WAVE_FORMAT_IEEE_FLOAT;
    format.nChannels = 2; format.nSamplesPerSec = 48000; format.wBitsPerSample = 32;
    format.nBlockAlign = 8; format.nAvgBytesPerSec = 384000;
    check(client->Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM |
        AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY, 1000000, 0, &format, nullptr), "initialize tone");
    ComPtr<IAudioRenderClient> render;
    check(client->GetService(IID_PPV_ARGS(&render)), "render service");
    UINT32 capacity = 0; check(client->GetBufferSize(&capacity), "render capacity");
    uint64_t frame = 0;
    check(client->Start(), "start tone");
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(static_cast<int>(seconds * 1000));
    while (std::chrono::steady_clock::now() < deadline) {
        UINT32 padding = 0; check(client->GetCurrentPadding(&padding), "padding");
        UINT32 count = capacity - padding;
        if (count) {
            BYTE* bytes = nullptr; check(render->GetBuffer(count, &bytes), "tone buffer");
            auto* pcm = reinterpret_cast<float*>(bytes);
            for (UINT32 i = 0; i < count; ++i, ++frame) {
                pcm[i * 2] = static_cast<float>(0.05 * std::sin(6.283185307179586 * left * frame / 48000));
                pcm[i * 2 + 1] = static_cast<float>(0.05 * std::sin(6.283185307179586 * right * frame / 48000));
            }
            check(render->ReleaseBuffer(count, 0), "release tone");
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    check(client->Stop(), "stop tone");
}
void record(const wchar_t* id, const wchar_t* filename, double seconds) {
    auto client = openClient(id);
    WAVEFORMATEX* format = nullptr; check(client->GetMixFormat(&format), "monitor format");
    struct FormatGuard { WAVEFORMATEX* value; ~FormatGuard() { CoTaskMemFree(value); } } guard{format};
    WORD tag = format->wFormatTag;
    if (tag == WAVE_FORMAT_EXTENSIBLE && format->cbSize >= 22)
        tag = static_cast<WORD>(reinterpret_cast<WAVEFORMATEXTENSIBLE*>(format)->SubFormat.Data1);
    if (format->nChannels != 2 || !((tag == WAVE_FORMAT_IEEE_FLOAT && format->wBitsPerSample == 32) ||
        (tag == WAVE_FORMAT_PCM && format->wBitsPerSample == 16)))
        throw std::runtime_error("Probe supports reported stereo float32/PCM16 monitor formats only");
    check(client->Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK, 1000000, 0, format, nullptr), "initialize monitor");
    ComPtr<IAudioCaptureClient> capture; check(client->GetService(IID_PPV_ARGS(&capture)), "capture service");
    std::ofstream out(filename, std::ios::binary);
    if (!out) throw std::runtime_error("Cannot open probe result file");
    uint32_t rate = format->nSamplesPerSec, channels = format->nChannels;
    out.write(reinterpret_cast<char*>(&rate), 4); out.write(reinterpret_cast<char*>(&channels), 4);
    check(client->Start(), "start monitor");
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(static_cast<int>(seconds * 1000));
    while (std::chrono::steady_clock::now() < deadline) {
        UINT32 packet = 0; check(capture->GetNextPacketSize(&packet), "next monitor packet");
        while (packet) {
            BYTE* data = nullptr; UINT32 frames = 0; DWORD flags = 0;
            check(capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr), "monitor packet");
            for (UINT32 i = 0; i < frames * channels; ++i) {
                float value = 0;
                if (!(flags & AUDCLNT_BUFFERFLAGS_SILENT)) {
                    value = tag == WAVE_FORMAT_IEEE_FLOAT ? reinterpret_cast<float*>(data)[i]
                        : reinterpret_cast<int16_t*>(data)[i] / 32768.0f;
                }
                out.write(reinterpret_cast<char*>(&value), 4);
            }
            check(capture->ReleaseBuffer(frames), "release monitor");
            check(capture->GetNextPacketSize(&packet), "next monitor packet");
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(3));
    }
    check(client->Stop(), "stop monitor");
}
int wmain(int argc, wchar_t** argv) {
    const HRESULT initialized = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    try {
        check(initialized, "COM");
        if (argc == 1) {
            std::vector<mux::EndpointInfo> endpoints;
            std::string error;
            if (!mux::AudioEngine::enumerateOutputs(endpoints, error)) throw std::runtime_error(error);
            std::cout << "WASAPI active render endpoint count: " << endpoints.size() << '\n';
        } else if (argc == 6 && std::wstring(argv[1]) == L"tone") {
            tone(argv[2], std::stod(argv[3]), std::stod(argv[4]), std::stod(argv[5]));
        } else if (argc == 5 && std::wstring(argv[1]) == L"record") {
            record(argv[2], argv[3], std::stod(argv[4]));
        } else throw std::runtime_error("Usage: probe [tone endpoint left_hz right_hz seconds | record endpoint file seconds]");
        if (SUCCEEDED(initialized)) CoUninitialize();
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << '\n';
        if (SUCCEEDED(initialized)) CoUninitialize();
        return 1;
    }
}
