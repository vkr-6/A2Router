#pragma once
// Process-loopback activation uses the public Windows 20348+ WASAPI API.
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <wrl/client.h>
#include <wrl/implements.h>
#include <string>
#include <cstdint>
#include <tlhelp32.h>
#include <map>

namespace a2r {
inline bool processCaptureSupported() {
    using Version = LONG (WINAPI*)(OSVERSIONINFOW*);
    auto fn = reinterpret_cast<Version>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion"));
    OSVERSIONINFOW version{}; version.dwOSVersionInfoSize = sizeof(version);
    return fn && fn(&version) == 0 && version.dwBuildNumber >= 20348;
}
inline std::wstring processImageFromHandle(HANDLE handle) {
    std::wstring path(32768, L'\0'); DWORD count = static_cast<DWORD>(path.size());
    if (!QueryFullProcessImageNameW(handle, 0, path.data(), &count)) return {};
    path.resize(count); return path;
}
inline std::wstring processImage(DWORD pid) {
    HANDLE handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!handle) return {};
    auto path = processImageFromHandle(handle); CloseHandle(handle); return path;
}
inline uint64_t processStamp(HANDLE handle) {
    FILETIME created{}, exited{}, kernel{}, user{};
    if (!GetProcessTimes(handle, &created, &exited, &kernel, &user)) return 0;
    return (uint64_t(created.dwHighDateTime) << 32) | created.dwLowDateTime;
}
inline bool processContainsRouter(DWORD target) {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) return true; // Fail closed if ancestry cannot be checked.
    std::map<DWORD, DWORD> parents;
    PROCESSENTRY32W entry{}; entry.dwSize = sizeof(entry);
    if (!Process32FirstW(snapshot, &entry)) { CloseHandle(snapshot); return true; }
    do { parents[entry.th32ProcessID] = entry.th32ParentProcessID; }
        while (Process32NextW(snapshot, &entry));
    CloseHandle(snapshot);
    DWORD current = GetCurrentProcessId();
    for (int depth = 0; depth < 64; ++depth) {
        if (current == target) return true;
        auto parent = parents.find(current);
        if (parent == parents.end() || !parent->second || parent->second == current) return false;
        current = parent->second;
    }
    return true;
}
class ProcessActivation final : public Microsoft::WRL::RuntimeClass<
    Microsoft::WRL::RuntimeClassFlags<Microsoft::WRL::ClassicCom>,
    Microsoft::WRL::FtmBase, IActivateAudioInterfaceCompletionHandler> {
public:
    HANDLE completed = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE process = nullptr;
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    HRESULT status = E_PENDING;
    Microsoft::WRL::ComPtr<IAudioClient> client;
    ~ProcessActivation() { if (completed) CloseHandle(completed); if (process) CloseHandle(process); }
    STDMETHOD(ActivateCompleted)(IActivateAudioInterfaceAsyncOperation* operation) override {
        HRESULT result = E_FAIL;
        Microsoft::WRL::ComPtr<IUnknown> object;
        status = operation->GetActivateResult(&result, &object);
        if (SUCCEEDED(status)) status = result;
        if (SUCCEEDED(status)) status = object ? object.As(&client) : E_NOINTERFACE;
        SetEvent(completed); return S_OK;
    }
};
inline HRESULT activateProcessCapture(DWORD pid, uint64_t stamp, IAudioClient** client) {
    if (!client || !pid || !stamp) return E_INVALIDARG;
    *client = nullptr;
    if (!processCaptureSupported()) return HRESULT_FROM_WIN32(ERROR_OLD_WIN_VERSION);
    if (processContainsRouter(pid)) return E_ACCESSDENIED; // Never feed our own process tree back into itself.
    auto activation = Microsoft::WRL::Make<ProcessActivation>();
    if (!activation || !activation->completed) return E_OUTOFMEMORY;
    activation->process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!activation->process || processStamp(activation->process) != stamp)
        return HRESULT_FROM_WIN32(ERROR_NOT_FOUND); // Never capture a recycled PID.
    activation->params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    activation->params.ProcessLoopbackParams.TargetProcessId = pid;
    activation->params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
    PROPVARIANT args{}; args.vt = VT_BLOB;
    args.blob.cbSize = sizeof(activation->params);
    args.blob.pBlobData = reinterpret_cast<BYTE*>(&activation->params);
    Microsoft::WRL::ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
    HRESULT hr = ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        __uuidof(IAudioClient), &args, activation.Get(), &operation);
    if (FAILED(hr)) return hr;
    if (WaitForSingleObject(activation->completed, 10000) != WAIT_OBJECT_0)
        return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
    if (FAILED(activation->status)) return activation->status;
    return activation->client.CopyTo(client);
}
}
