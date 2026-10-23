// a2router C ABI. Each selected source owns an existing WASAPI AudioEngine.
// Multiple engines render shared-mode streams; Windows performs their mixing.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
// Instantiate SDK property keys (including PKEY_AudioEngine_DeviceFormat)
// in this translation unit instead of relying on an SDK import-library symbol.
// This must precede all SDK headers so DEFINE_PROPERTYKEY sees INITGUID.
#include <initguid.h>
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
#include "WindowsEndpointControl.h"

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
std::string cableServiceInstance(IMMDevice* device) {
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
        wchar_t service[512]{}; ULONG length = sizeof(service), type = 0;
        if (CM_Get_DevNode_Registry_PropertyW(node, CM_DRP_SERVICE, &type, service, &length, 0) == CR_SUCCESS
                && type == REG_SZ && _wcsicmp(service, L"VBAudioVACMME") == 0) {
            wchar_t instance[MAX_DEVICE_ID_LEN]{};
            if (CM_Get_Device_IDW(node, instance, MAX_DEVICE_ID_LEN, 0) == CR_SUCCESS) return utf8(instance);
        }
        DEVINST parent = 0;
        if (CM_Get_Parent(&parent, node, 0) != CR_SUCCESS) break;
        node = parent;
    }
    return {};
}
// MMDevice software endpoint parents do not necessarily lead to the audio
// adapter. Follow the documented topology connector to the hardware device.
std::string vbCableInstance(IMMDevice* device) {
    auto instance = cableServiceInstance(device);
    if (!instance.empty()) return instance;
    ComPtr<IDeviceTopology> topology;
    if (SUCCEEDED(device->Activate(__uuidof(IDeviceTopology), CLSCTX_ALL, nullptr,
            reinterpret_cast<void**>(topology.GetAddressOf())))) {
        ComPtr<IConnector> connector;
        LPWSTR connectedId = nullptr;
        if (SUCCEEDED(topology->GetConnector(0, &connector)) &&
            SUCCEEDED(connector->GetDeviceIdConnectedTo(&connectedId))) {
            auto adapter = a2r::endpoint(connectedId);
            CoTaskMemFree(connectedId);
            if (adapter) instance = cableServiceInstance(adapter.Get());
        }
    }
    return instance;
}
std::wstring interfaceName(IMMDevice* device) {
    ComPtr<IPropertyStore> properties;
    PROPVARIANT value; PropVariantInit(&value);
    std::wstring name;
    if (SUCCEEDED(device->OpenPropertyStore(STGM_READ, &properties)) &&
        SUCCEEDED(properties->GetValue(PKEY_DeviceInterface_FriendlyName, &value)) &&
        value.vt == VT_LPWSTR && value.pwszVal) name = value.pwszVal;
    PropVariantClear(&value); return name;
}
void writeDevice(std::ostream& out, IMMDevice* device, const std::wstring& name, bool input, bool isDefault) {
    out << "{\"id\":" << quote(utf8(deviceId(device))) << ",\"name\":" << quote(utf8(name))
        << ",\"kind\":" << quote(input ? "input" : "output") << ",\"default\":" << (isDefault ? "true" : "false");
    auto cable = vbCableInstance(device);
    const auto adapterName = interfaceName(device);
    // Exact immutable adapter branding is a fallback, never an endpoint-name guess.
    const bool branded = _wcsicmp(adapterName.c_str(), L"VB-Audio Virtual Cable") == 0 ||
                         _wcsicmp(adapterName.c_str(), L"VB-Audio Point") == 0;
    if (cable.empty() && branded) cable = "base";
    if (!cable.empty()) out << ",\"virtual\":true";
    out << ",\"properties\":{\"interface_name\":" << quote(utf8(adapterName));
    if (!cable.empty()) out << ",\"virtual_driver\":\"VB-CABLE\",\"feedback_group\":" << quote("vbcable:base");
    out << ",\"controls\":"; a2r::controls(out, device);
    ComPtr<IPropertyStore> deviceProperties;
    PROPVARIANT configured; PropVariantInit(&configured);
    if (SUCCEEDED(device->OpenPropertyStore(STGM_READ, &deviceProperties)) &&
        SUCCEEDED(deviceProperties->GetValue(PKEY_AudioEngine_DeviceFormat, &configured)) &&
        configured.vt == VT_BLOB && configured.blob.cbSize >= sizeof(WAVEFORMATEX)) {
        auto* f = reinterpret_cast<const WAVEFORMATEX*>(configured.blob.pBlobData);
        if (configured.blob.cbSize >= sizeof(WAVEFORMATEX) + f->cbSize) {
            out << ",\"device_format\":"; a2r::writeFormat(out, f);
        }
    }
    PropVariantClear(&configured);
    out << '}';
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
bool startSession(const std::wstring& source, bool input, const wchar_t* ids, const wchar_t* delayList = nullptr, const wchar_t* matrixList = nullptr) {
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
    std::wistringstream matrixLines(matrixList ? matrixList : L"");
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
        mux::OutputRequest request;
        request.endpoint_id = id; request.relative_delay_ms = delay;
        if (matrixList) {
            std::wstring row;
            if (!std::getline(matrixLines, row)) { error = "One matrix row required per output"; return false; }
            std::wistringstream entries(row);
            size_t count = 0;
            if (!(entries >> count) || count > 1024) { error = "Invalid matrix size"; return false; }
            for (size_t i = 0; i < count; ++i) {
                mux::ChannelConnection connection;
                if (!(entries >> connection.source >> connection.destination >> connection.gain)) {
                    error = "Invalid channel connection"; return false;
                }
                request.channel_map.push_back(connection);
            }
            std::wstring extra;
            if (entries >> extra) { error = "Extra matrix values"; return false; }
        }
        config.outputs.push_back(std::move(request));
    }
    std::wstring extraMatrix;
    if (matrixList && std::getline(matrixLines, extraMatrix)) { error = "Extra matrix rows"; return false; }
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
        << ",\"sample_rate\":" << stats.mix_sample_rate << ",\"block_align\":" << stats.mix_block_align << ",\"capture_poll_timeouts\":" << stats.capture_poll_timeouts << ",\"devices\":[";
    bool first = true;
    for (const auto& device : stats.devices) {
        if (!first) out << ',';
        first = false;
        out << "{\"id\":" << quote(utf8(device.endpoint_id)) << ",\"faulted\":" << (device.faulted ? "true" : "false")
            << ",\"running\":" << (device.running ? "true" : "false") << ",\"fill_bytes\":" << device.fill_bytes
            << ",\"target_bytes\":" << device.target_bytes << ",\"sample_rate\":" << device.sample_rate_hz
            << ",\"clipped_samples\":" << device.clipped_samples
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
API int ar_vbcable_discovery_version() { return 1; }
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
API int ar_source_set_delay(const wchar_t* source, int input, const wchar_t* destination, int64_t delayMs) {
    std::lock_guard<std::mutex> lock(apiMutex);
    try {
        if (!source || !destination) { error = "Source and destination are required"; return 0; }
        auto found = sessions.find(source);
        if (found == sessions.end() || found->second.input != (input != 0)) {
            error = "Native source session is not running"; return 0;
        }
        const auto stats = found->second.engine->stats();
        for (size_t i = 0; i < stats.devices.size(); ++i) {
            if (stats.devices[i].endpoint_id == destination) {
                return found->second.engine->setDeviceDelay(static_cast<int>(i), delayMs, error) ? 1 : 0;
            }
        }
        error = "Destination is not in this source session"; return 0;
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

API int ar_source_start_matrix(const wchar_t* source, int input, const wchar_t* ids,
                               const wchar_t* delays, const wchar_t* matrices) {
    std::lock_guard<std::mutex> lock(apiMutex);
    try {
        if (!source || !*source || !ids || !delays || !matrices) { error = "Missing matrix routing arguments"; return 0; }
        return startSession(source, input != 0, ids, delays, matrices) ? 1 : 0;
    } catch (const std::exception& e) { error = e.what(); return 0; }
}

API const char* ar_controls() {
    std::lock_guard<std::mutex> lock(apiMutex);
    try {
        ComScope scope;
        if (!scope.usable()) { error = "COM initialization failed"; return nullptr; }
        ComPtr<IMMDeviceEnumerator> e;
        if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&e)))) {
            error = "Cannot enumerate endpoint controls"; return nullptr;
        }
        ComPtr<IMMDeviceCollection> devices;
        if (FAILED(e->EnumAudioEndpoints(eAll, DEVICE_STATE_ACTIVE, &devices))) return nullptr;
        UINT count = 0; devices->GetCount(&count);
        std::ostringstream out; out.imbue(std::locale::classic()); out << '['; bool first = true;
        for (UINT i = 0; i < count; ++i) {
            ComPtr<IMMDevice> device;
            if (FAILED(devices->Item(i, &device))) continue;
            if (!first) out << ','; first = false;
            out << "{\"id\":" << quote(utf8(deviceId(device.Get()))) << ",\"controls\":";
            a2r::controls(out, device.Get()); out << '}';
        }
        out << ']'; result = out.str(); error.clear(); return result.c_str();
    } catch (const std::exception& e) { error = e.what(); return nullptr; }
}
API int ar_set_device_volume(const wchar_t* id, float level) {
    std::lock_guard<std::mutex> lock(apiMutex);
    ComScope scope;
    ComPtr<IMMDevice> device;
    if (scope.usable()) device = a2r::endpoint(id);
    ComPtr<IAudioEndpointVolume> volume;
    if (!device || !std::isfinite(level) || level < 0 || level > 1 ||
        FAILED(device->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr, reinterpret_cast<void**>(volume.GetAddressOf()))) ||
        FAILED(volume->SetMasterVolumeLevelScalar(level, nullptr))) { error = "Cannot set endpoint volume"; return 0; }
    error.clear(); return 1;
}
API int ar_set_device_mute(const wchar_t* id, int muted) {
    std::lock_guard<std::mutex> lock(apiMutex);
    ComScope scope;
    ComPtr<IMMDevice> device;
    if (scope.usable()) device = a2r::endpoint(id);
    ComPtr<IAudioEndpointVolume> volume;
    if (!device || FAILED(device->Activate(__uuidof(IAudioEndpointVolume), CLSCTX_ALL, nullptr,
        reinterpret_cast<void**>(volume.GetAddressOf()))) || FAILED(volume->SetMute(muted != 0, nullptr))) {
        error = "Cannot set endpoint mute"; return 0;
    }
    error.clear(); return 1;
}
API const char* ar_device_formats(const wchar_t* id) {
    std::lock_guard<std::mutex> lock(apiMutex);
    ComScope scope;
    ComPtr<IMMDevice> device;
    if (scope.usable()) device = a2r::endpoint(id);
    ComPtr<IAudioClient> client;
    if (!device || FAILED(device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
        reinterpret_cast<void**>(client.GetAddressOf())))) { error = "Cannot query device formats"; return nullptr; }
    std::ostringstream out; out << '['; bool first = true;
    for (int channels : {1, 2, 4, 6, 8, 16}) for (int rate : {44100, 48000, 88200, 96000, 192000})
        for (int encoding = 0; encoding < 5; ++encoding) {
            const int bits = encoding == 0 ? 16 : encoding < 3 ? 24 : 32;
            const int container = encoding == 0 ? 16 : encoding == 1 ? 24 : 32;
            auto format = a2r::format(channels, rate, bits, encoding == 4, container);
            if (client->IsFormatSupported(AUDCLNT_SHAREMODE_EXCLUSIVE, &format.Format, nullptr) == S_OK) {
                if (!first) out << ','; first = false; a2r::writeFormat(out, &format.Format);
            }
        }
    out << ']'; result = out.str(); error.clear(); return result.c_str();
}
API int ar_set_device_format(const wchar_t* id, int channels, int rate, int bits, int floating, int container) {
    std::lock_guard<std::mutex> lock(apiMutex);
    if ((channels != 1 && channels != 2 && channels != 4 && channels != 6 && channels != 8 && channels != 16) ||
        rate < 8000 || rate > 192000 || (bits != 16 && bits != 24 && bits != 32) ||
        (container != 16 && container != 24 && container != 32) || bits > container ||
        (floating && (bits != 32 || container != 32))) { error = "Invalid endpoint format"; return 0; }
    ComScope scope;
    ComPtr<IMMDevice> device;
    if (scope.usable()) device = a2r::endpoint(id);
    ComPtr<IAudioClient> client;
    if (!device || FAILED(device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
        reinterpret_cast<void**>(client.GetAddressOf())))) { error = "Endpoint unavailable"; return 0; }
    auto format = a2r::format(channels, rate, bits, floating != 0, container);
    if (client->IsFormatSupported(AUDCLNT_SHAREMODE_EXCLUSIVE, &format.Format, nullptr) != S_OK) {
        error = "The driver rejected this exact format"; return 0;
    }
    auto policy = a2r::policy();
    if (!policy) { error = "This Windows version does not expose format configuration; use Windows Sound"; return 0; }
    WAVEFORMATEX* old = nullptr;
    if (FAILED(policy->GetDeviceFormat(id, 0, &old)) || !old) { CoTaskMemFree(old); error = "Cannot preserve previous endpoint format"; return 0; }
    const HRESULT applied = policy->SetDeviceFormat(id, &format.Format, nullptr);
    WAVEFORMATEX* actual = nullptr;
    const bool verified = SUCCEEDED(applied) && SUCCEEDED(policy->GetDeviceFormat(id, 0, &actual)) && a2r::sameFormat(actual, &format.Format);
    CoTaskMemFree(actual);
    if (!verified) {
        const HRESULT rollback = policy->SetDeviceFormat(id, old, nullptr);
        WAVEFORMATEX* restoredFormat = nullptr;
        const bool restored = SUCCEEDED(rollback) && SUCCEEDED(policy->GetDeviceFormat(id, 0, &restoredFormat))
                              && a2r::sameFormat(old, restoredFormat);
        CoTaskMemFree(restoredFormat); CoTaskMemFree(old);
        error = restored ? "Format was rejected or not verified; previous format restored. Close audio apps and retry."
                         : "Format was not verified and restoring the old format could not be verified; inspect Windows Sound";
        return 0;
    }
    CoTaskMemFree(old); error.clear(); return 1;
}
API int ar_rename_device(const wchar_t* id, const wchar_t* name) {
    std::lock_guard<std::mutex> lock(apiMutex);
    if (!name || !*name || wcslen(name) > 128) { error = "Invalid endpoint name"; return 0; }
    ComScope scope;
    ComPtr<IMMDevice> device;
    if (scope.usable()) device = a2r::endpoint(id);
    ComPtr<IPropertyStore> properties;
    if (!device || FAILED(device->OpenPropertyStore(STGM_READWRITE, &properties))) {
        error = "Windows requires administrator access to rename this endpoint"; return 0;
    }
    const auto previous = friendlyName(device.Get());
    PROPVARIANT value; PropVariantInit(&value); value.vt = VT_LPWSTR; value.pwszVal = const_cast<wchar_t*>(name);
    if (FAILED(properties->SetValue(PKEY_Device_FriendlyName, value)) || FAILED(properties->Commit())) {
        value.pwszVal = const_cast<wchar_t*>(previous.c_str());
        const bool restored = SUCCEEDED(properties->SetValue(PKEY_Device_FriendlyName, value)) &&
                              SUCCEEDED(properties->Commit()) && friendlyName(device.Get()) == previous;
        error = restored ? "Windows rejected the endpoint name; previous name retained" : "Endpoint rename failed; previous name could not be verified";
        return 0;
    }
    if (friendlyName(device.Get()) != name) {
        value.pwszVal = const_cast<wchar_t*>(previous.c_str());
        const bool restored = SUCCEEDED(properties->SetValue(PKEY_Device_FriendlyName, value)) && SUCCEEDED(properties->Commit());
        error = restored ? "Endpoint rename was not verified; previous name restored" : "Endpoint rename was not verified and rollback failed";
        return 0;
    }
    error.clear(); return 1;
}
