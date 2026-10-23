#pragma once
// Windows-only endpoint controls. All calls run on the serialized control worker.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <mmdeviceapi.h>
#include <Audioclient.h>
#include <mmreg.h>
#include <wrl/client.h>
#include <algorithm>
#include <ostream>
#include <endpointvolume.h>
#include <devicetopology.h>
#include <cmath>
#include <locale>

namespace a2r {
using Microsoft::WRL::ComPtr;
inline ComPtr<IMMDevice> endpoint(const wchar_t* id) {
    ComPtr<IMMDeviceEnumerator> e;
    ComPtr<IMMDevice> device;
    if (id && SUCCEEDED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&e))))
        e->GetDevice(id, &device);
    return device;
}
inline void controls(std::ostream& out, IMMDevice* device) {
    out << '{';
    ComPtr<IAudioEndpointVolume> volume;
    float level = 0; BOOL muted = FALSE;
    const bool hasVolume = SUCCEEDED(device->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr,
        reinterpret_cast<void**>(volume.GetAddressOf()))) &&
        SUCCEEDED(volume->GetMasterVolumeLevelScalar(&level)) && std::isfinite(level) && SUCCEEDED(volume->GetMute(&muted));
    out << "\"volume_available\":" << (hasVolume ? "true" : "false");
    if (hasVolume) out << ",\"volume\":" << std::clamp(level, 0.0f, 1.0f) << ",\"muted\":" << (muted ? "true" : "false");
    ComPtr<IAudioMeterInformation> meter;
    float peak = 0;
    const bool hasPeak = SUCCEEDED(device->Activate(__uuidof(IAudioMeterInformation), CLSCTX_ALL, nullptr,
        reinterpret_cast<void**>(meter.GetAddressOf()))) && SUCCEEDED(meter->GetPeakValue(&peak)) && std::isfinite(peak);
    out << ",\"peak_available\":" << (hasPeak ? "true" : "false");
    if (hasPeak) out << ",\"peak\":" << std::clamp(peak, 0.0f, 1.0f);
    out << '}';
}
// Windows exposes no documented shared-default-format setter. Keep this exact
// compatibility interface isolated; QI failure is reported, never simulated.
// Only the four methods following IUnknown are used. No default-device API.
struct __declspec(uuid("f8679f50-850a-41cf-9c72-430f290290c8")) FormatPolicy : IUnknown {
    virtual HRESULT STDMETHODCALLTYPE GetMixFormat(PCWSTR, WAVEFORMATEX**) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetDeviceFormat(PCWSTR, INT, WAVEFORMATEX**) = 0;
    virtual HRESULT STDMETHODCALLTYPE ResetDeviceFormat(PCWSTR) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetDeviceFormat(PCWSTR, WAVEFORMATEX*, WAVEFORMATEX*) = 0;
};
inline ComPtr<FormatPolicy> policy() {
    const CLSID clsid = {0x870af99c, 0x171d, 0x4f9e, {0xaf, 0x0d, 0xe6, 0x3d, 0xf4, 0x0c, 0x2b, 0xc9}};
    ComPtr<FormatPolicy> result;
    CoCreateInstance(clsid, nullptr, CLSCTX_ALL, __uuidof(FormatPolicy), reinterpret_cast<void**>(result.GetAddressOf()));
    return result;
}
inline WAVEFORMATEXTENSIBLE format(int channels, int rate, int bits, bool floating, int container) {
    WAVEFORMATEXTENSIBLE f{};
    f.Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE;
    f.Format.nChannels = static_cast<WORD>(channels);
    f.Format.nSamplesPerSec = rate;
    f.Format.wBitsPerSample = static_cast<WORD>(container);
    f.Format.nBlockAlign = static_cast<WORD>(channels * container / 8);
    f.Format.nAvgBytesPerSec = rate * f.Format.nBlockAlign;
    f.Format.cbSize = 22;
    f.Samples.wValidBitsPerSample = static_cast<WORD>(bits);
    f.dwChannelMask = channels == 1 ? 4 : channels == 2 ? 3 : channels == 4 ? 0x33 : channels == 6 ? 0x3f : channels == 8 ? 0x63f : 0;
    f.SubFormat = {static_cast<unsigned long>(floating ? WAVE_FORMAT_IEEE_FLOAT : WAVE_FORMAT_PCM), 0, 0x10,
                  {0x80, 0, 0, 0xaa, 0, 0x38, 0x9b, 0x71}};
    return f;
}
inline bool sameFormat(const WAVEFORMATEX* a, const WAVEFORMATEX* b) {
    if (!a || !b || a->nChannels != b->nChannels || a->nSamplesPerSec != b->nSamplesPerSec || a->wBitsPerSample != b->wBitsPerSample) return false;
    const auto tag = [](const WAVEFORMATEX* f) { return f->wFormatTag == WAVE_FORMAT_EXTENSIBLE && f->cbSize >= 22
        ? reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(f)->SubFormat.Data1 : DWORD(f->wFormatTag); };
    const auto valid = [](const WAVEFORMATEX* f) { return f->wFormatTag == WAVE_FORMAT_EXTENSIBLE && f->cbSize >= 22
        ? reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(f)->Samples.wValidBitsPerSample : f->wBitsPerSample; };
    return tag(a) == tag(b) && valid(a) == valid(b);
}
inline void writeFormat(std::ostream& out, const WAVEFORMATEX* f) {
    WORD bits = f->wBitsPerSample; DWORD tag = f->wFormatTag;
    if (tag == WAVE_FORMAT_EXTENSIBLE && f->cbSize >= 22) {
        auto* ext = reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(f);
        bits = ext->Samples.wValidBitsPerSample; tag = ext->SubFormat.Data1;
    }
    out << "{\"channels\":" << f->nChannels << ",\"sample_rate\":" << f->nSamplesPerSec
        << ",\"bits\":" << bits << ",\"container_bits\":" << f->wBitsPerSample
        << ",\"encoding\":\"" << (tag == WAVE_FORMAT_IEEE_FLOAT ? "float" : "pcm") << "\"}";
}
} // namespace a2r
