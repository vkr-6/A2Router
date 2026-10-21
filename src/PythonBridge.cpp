// a2router C ABI. Each selected source owns an existing WASAPI AudioEngine.
// Multiple engines render shared-mode streams; Windows performs their mixing.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmdeviceapi.h>
#include <Audioclient.h>
#include <mmreg.h>
#include <cfgmgr32.h>
#include <Functiondiscoverykeys_devpkey.h>
#include <wrl/client.h>
#include "AudioEngine.h"
#include <algorithm>
#include <chrono>
#include <map>
#include <mutex>
#include <sstream>
#include <thread>

using Microsoft::WRL::ComPtr;
namespace {
struct Session { std::unique_ptr<mux::AudioEngine> engine; bool input = false; };
std::map<std::wstring, Session> sessions;
std::string result, error;
std::mutex apiMutex; // Serializes only the control ABI, never realtime callbacks.
std::string utf8(const std::wstring& s) {
    if (s.empty()) return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0, nullptr, nullptr);
    std::string out(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), n, nullptr, nullptr);
    return out;
}
std::string quote(const std::string& s) {
    std::string out = "\"";
    for (unsigned char c : s) {
        if (c == '\\' || c == '"') { out += '\\'; out += static_cast<char>(c); }
        else if (c < 32) {
            const char* hex = "0123456789abcdef";
            out += "\\u00"; out += hex[c >> 4]; out += hex[c & 15];
        } else out += static_cast<char>(c);
    }
    return out + "\"";
}
struct ComScope {
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    ~ComScope() { if (SUCCEEDED(hr)) CoUninitialize(); }
    bool usable() const { return SUCCEEDED(hr) || hr == RPC_E_CHANGED_MODE; }
};
std::wstring deviceId(IMMDevice* device) {
    LPWSTR raw = nullptr;
    if (FAILED(device->GetId(&raw))) return {};
    std::wstring id(raw); CoTaskMemFree(raw); return id;
}
std::wstring friendlyName(IMMDevice* device) {
    ComPtr<IPropertyStore> properties;
    if (FAILED(device->OpenPropertyStore(STGM_READ, &properties))) return L"Unknown endpoint";
    PROPVARIANT value; PropVariantInit(&value);
    std::wstring name = L"Unknown endpoint";
    if (SUCCEEDED(properties->GetValue(PKEY_Device_FriendlyName, &value)) && value.vt == VT_LPWSTR && value.pwszVal)
        name = value.pwszVal;
    PropVariantClear(&value); return name;
}
std::string managedInstance(IMMDevice* device) {
    ComPtr<IPropertyStore> properties;
    if (FAILED(device->OpenPropertyStore(STGM_READ, &properties))) return {};
    PROPVARIANT value; PropVariantInit(&value);
    std::wstring id;
    if (SUCCEEDED(properties->GetValue(PKEY_Device_InstanceId, &value)) && value.vt == VT_LPWSTR && value.pwszVal)
        id = value.pwszVal;
    PropVariantClear(&value);
    DEVINST node = 0;
    if (id.empty() || CM_Locate_DevNodeW(&node, id.data(), CM_LOCATE_DEVNODE_NORMAL) != CR_SUCCESS) return {};
    for (int depth = 0; depth < 16; ++depth) {
        wchar_t current[MAX_DEVICE_ID_LEN]{};
        if (CM_Get_Device_IDW(node, current, MAX_DEVICE_ID_LEN, 0) != CR_SUCCESS) break;
        const std::wstring prefix = L"ROOT\\A2ROUTER\\";
        if (_wcsnicmp(current, prefix.c_str(), prefix.size()) == 0) return utf8(current + prefix.size());
        DEVINST parent = 0;
        if (CM_Get_Parent(&parent, node, 0) != CR_SUCCESS) break;
        node = parent;
    }
    return {};
}
void writeDevice(std::ostream& out, IMMDevice* device, const std::wstring& name, bool input, bool isDefault) {
    out << "{\"id\":" << quote(utf8(deviceId(device))) << ",\"name\":" << quote(utf8(name))
        << ",\"kind\":" << quote(input ? "input" : "output") << ",\"default\":" << (isDefault ? "true" : "false");
    const auto managed = managedInstance(device);
    if (!managed.empty()) out << ",\"virtual\":true,\"properties\":{\"a2router_instance\":" << quote(managed) << '}';
    ComPtr<IAudioClient> client;
    if (SUCCEEDED(device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
            reinterpret_cast<void**>(client.GetAddressOf())))) {
        WAVEFORMATEX* format = nullptr;
        if (SUCCEEDED(client->GetMixFormat(&format))) {
            DWORD mask = 0;
            WORD tag = format->wFormatTag;
            if (format->wFormatTag == WAVE_FORMAT_EXTENSIBLE && format->cbSize >= 22) {
                auto* extended = reinterpret_cast<WAVEFORMATEXTENSIBLE*>(format);
                mask = extended->dwChannelMask;
                tag = static_cast<WORD>(extended->SubFormat.Data1);
            }
            std::string encoding = tag == WAVE_FORMAT_IEEE_FLOAT ? "float" : (tag == WAVE_FORMAT_PCM ? "pcm" : "wave-tag-" + std::to_string(tag));
            out << ",\"channels\":" << format->nChannels << ",\"sample_rate\":" << format->nSamplesPerSec
                << ",\"sample_format\":" << quote(encoding + std::to_string(format->wBitsPerSample) + "le")
                << ",\"positions\":[";
            const char* names[] = {"front-left", "front-right", "front-center", "lfe", "rear-left", "rear-right",
                "front-left-of-center", "front-right-of-center", "rear-center", "side-left", "side-right", "top-center",
                "top-front-left", "top-front-center", "top-front-right", "top-rear-left", "top-rear-center", "top-rear-right"};
            bool first = true;
            for (int bit = 0; bit < 18; ++bit) if (mask & (1u << bit)) {
                if (!first) out << ',';
                out << quote(names[bit]); first = false;
            }
            // WAVEFORMATEX defines conventional mono/stereo order without a mask.
            if (!mask && format->nChannels == 1) out << quote("mono");
            if (!mask && format->nChannels == 2) out << quote("front-left") << ',' << quote("front-right");
            out << ']';
            CoTaskMemFree(format);
        }
        REFERENCE_TIME normal = 0, minimum = 0;
        if (SUCCEEDED(client->GetDevicePeriod(&normal, &minimum)))
            out << ",\"latency\":{\"default_period_us\":" << normal / 10 << ",\"minimum_period_us\":" << minimum / 10 << '}';
    }
    out << '}';
}
bool startSession(const std::wstring& source, bool input, const wchar_t* ids, const wchar_t* delayList = nullptr) {
    auto& session = sessions[source];
    if (!session.engine) session.engine = std::make_unique<mux::AudioEngine>();
    session.engine->stop();
    session.input = input;
    mux::EngineConfig config;
    config.capture_endpoint_id = source;
    config.capture_from_input = input;
    std::wistringstream lines(ids ? ids : L"");
    std::wistringstream delayLines(delayList ? delayList : L"");
    config.normalize_output_delays = delayList == nullptr;
    std::wstring id;
    while (std::getline(lines, id)) if (!id.empty()) {
        if (std::any_of(config.outputs.begin(), config.outputs.end(), [&](const auto& output) { return output.endpoint_id == id; })) {
            error = "Duplicate native output endpoint"; return false;
        }
        int64_t delay = 0;
        if (delayList) {
            std::wstring line;
            if (!std::getline(delayLines, line) || line.empty() ||
                line.find_first_not_of(L"0123456789") != std::wstring::npos) {
                error = "One nonnegative delay is required per output"; return false;
            }
            delay = std::stoll(line);
            if (delay > config.max_delay_ms) { error = "Delay exceeds 10000 ms"; return false; }
        }
        config.outputs.push_back({id, delay});
    }
    std::wstring extraDelay;
    if (delayList && std::getline(delayLines, extraDelay)) { error = "Extra output delay values"; return false; }
    if (config.outputs.empty()) { sessions.erase(source); error.clear(); return true; }
    if (!session.engine->start(config, error)) return false;
    for (int i = 0; i < 100; ++i) {
        auto stats = session.engine->stats();
        if (stats.running && stats.devices.size() == config.outputs.size()) {
            bool healthy = true;
            for (const auto& device : stats.devices) healthy = healthy && device.running && !device.faulted;
            if (healthy) { error.clear(); return true; }
        }
        if (session.engine->state() == mux::EngineState::Faulted) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    session.engine->stop();
    error = "WASAPI startup incomplete or faulted; this source's requested outputs stopped";
    return false;
}
void writeStats(std::ostream& out, const std::wstring& source, const Session& session) {
    const auto stats = session.engine->stats();
    out << "{\"source_id\":" << quote(utf8(source)) << ",\"capture_from_input\":" << (session.input ? "true" : "false")
        << ",\"running\":" << (session.engine->isRunning() ? "true" : "false")
        << ",\"sample_rate\":" << stats.mix_sample_rate << ",\"capture_poll_timeouts\":" << stats.capture_poll_timeouts << ",\"devices\":[";
    bool first = true;
    for (const auto& device : stats.devices) {
        if (!first) out << ',';
        first = false;
        out << "{\"id\":" << quote(utf8(device.endpoint_id)) << ",\"faulted\":" << (device.faulted ? "true" : "false")
            << ",\"running\":" << (device.running ? "true" : "false") << ",\"fill_bytes\":" << device.fill_bytes
            << ",\"target_bytes\":" << device.target_bytes << ",\"sample_rate\":" << device.sample_rate_hz
            << ",\"overflows\":" << device.overflow_count << ",\"underflows\":" << device.partial_underflow_count + device.catastrophic_underflow_count
            << ",\"delay_ms\":" << device.configured_delay_ms
            << ",\"max_live_delay_ms\":" << device.max_delay_ms_for_device
            << ",\"delay_adjusting\":" << (device.delay_adjust_in_flight ? "true" : "false")
            << ",\"prebuffering\":" << (device.prebuffering ? "true" : "false")
            << ",\"ema_error\":" << device.ema_error
            << ",\"capacity_bytes\":" << device.capacity_bytes
            << ",\"api_errors\":" << device.api_error_count << '}';
    }
    out << "]}";
}
}
#define API extern "C" __declspec(dllexport)
API int ar_api_version() { return 2; }
API int ar_virtual_discovery_version() { return 1; }
API const char* ar_error() { return error.c_str(); }
API const char* ar_devices() {
    std::lock_guard<std::mutex> lock(apiMutex);
    try {
        ComScope scope;
        if (!scope.usable()) { error = "COM initialization failed"; return nullptr; }
        ComPtr<IMMDeviceEnumerator> enumerator;
        if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&enumerator)))) {
            error = "Cannot create endpoint enumerator"; return nullptr;
        }
        std::ostringstream out; out << '[';
        bool first = true;
        for (EDataFlow flow : {eRender, eCapture}) {
            ComPtr<IMMDevice> defaultDevice;
            enumerator->GetDefaultAudioEndpoint(flow, eConsole, &defaultDevice);
            const auto defaultId = defaultDevice ? deviceId(defaultDevice.Get()) : std::wstring();
            ComPtr<IMMDeviceCollection> collection;
            if (FAILED(enumerator->EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE, &collection))) {
                error = "Cannot enumerate active audio endpoints"; return nullptr;
            }
            UINT count = 0;
            if (FAILED(collection->GetCount(&count))) { error = "Cannot count audio endpoints"; return nullptr; }
            for (UINT i = 0; i < count; ++i) {
                ComPtr<IMMDevice> device;
                if (FAILED(collection->Item(i, &device))) continue;
                if (!first) out << ',';
                first = false;
                writeDevice(out, device.Get(), friendlyName(device.Get()), flow == eCapture, deviceId(device.Get()) == defaultId);
            }
        }
        out << ']'; result = out.str(); error.clear(); return result.c_str();
    } catch (const std::exception& exc) { error = exc.what(); return nullptr; }
}
API int ar_source_start(const wchar_t* source, int captureFromInput, const wchar_t* ids) {
    std::lock_guard<std::mutex> lock(apiMutex);
    try {
        if (!source || !*source) { error = "Explicit source endpoint ID required"; return 0; }
        return startSession(source, captureFromInput != 0, ids) ? 1 : 0;
    } catch (const std::exception& exc) { error = exc.what(); return 0; }
}
API int ar_source_start_delays(const wchar_t* source, int input, const wchar_t* ids, const wchar_t* delays) {
    std::lock_guard<std::mutex> lock(apiMutex);
    try {
        if (!source || !*source || !delays) { error = "Source and delay list required"; return 0; }
        return startSession(source, input != 0, ids, delays) ? 1 : 0;
    } catch (const std::exception& exc) { error = exc.what(); return 0; }
}
API int ar_start(const wchar_t* ids) {
    std::lock_guard<std::mutex> lock(apiMutex);
    try { return startSession(L"", false, ids) ? 1 : 0; }
    catch (const std::exception& exc) { error = exc.what(); return 0; }
}
API const char* ar_stats() {
    std::lock_guard<std::mutex> lock(apiMutex);
    try {
        std::ostringstream out;
        bool running = false;
        for (const auto& item : sessions) running = running || item.second.engine->isRunning();
        out << "{\"running\":" << (running ? "true" : "false") << ",\"sessions\":[";
        bool first = true;
        for (const auto& item : sessions) {
            if (!first) out << ',';
            first = false;
            writeStats(out, item.first, item.second);
        }
        out << "]}"; result = out.str(); return result.c_str();
    } catch (const std::exception& exc) { error = exc.what(); return nullptr; }
}
API void ar_close() {
    std::lock_guard<std::mutex> lock(apiMutex);
    sessions.clear();
}
