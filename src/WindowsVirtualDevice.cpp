// Elevated control helper. Creates/removes only ROOT\A2ROUTER\<UUID> devnodes.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <setupapi.h>
#include <newdev.h>
#include <cfgmgr32.h>
#include <initguid.h>
#include <devguid.h>
#include <mmdeviceapi.h>
#include <functiondiscoverykeys_devpkey.h>
#include <propvarutil.h>
#include <wrl/client.h>
#include <string>
#include <vector>
#include <cwctype>
#include <cwchar>
using Microsoft::WRL::ComPtr;
namespace {
constexpr wchar_t hardware[] = L"ROOT\\A2RouterAudio\0"; // REG_MULTI_SZ double NUL
struct DeviceSet { HDEVINFO h = INVALID_HANDLE_VALUE; ~DeviceSet() { if(h != INVALID_HANDLE_VALUE) SetupDiDestroyDeviceInfoList(h); } };
bool validId(const std::wstring& id) {
    if(id.size() != 36) return false;
    for(size_t i=0;i<id.size();++i) {
        if(i==8 || i==13 || i==18 || i==23) { if(id[i]!=L'-') return false; }
        else if(!iswxdigit(id[i])) return false;
    }
    return true;
}
std::wstring instance(const std::wstring& id) {
    std::wstring s=L"ROOT\\A2ROUTER\\";
    for(auto ch:id) if(ch!=L'-') s+=static_cast<wchar_t>(towupper(ch));
    return s;
}
DWORD checkOwner(HDEVINFO set, SP_DEVINFO_DATA& dev) {
    wchar_t ids[256]{}; DWORD type=0;
    if(!SetupDiGetDeviceRegistryPropertyW(set,&dev,SPDRP_HARDWAREID,&type,
        reinterpret_cast<PBYTE>(ids),sizeof(ids),nullptr)) return GetLastError();
    return type==REG_MULTI_SZ && _wcsicmp(ids,hardware)==0 ? ERROR_SUCCESS : ERROR_ACCESS_DENIED;
}
DWORD removeDevice(HDEVINFO set, SP_DEVINFO_DATA& dev) {
    SP_REMOVEDEVICE_PARAMS p{}; p.ClassInstallHeader.cbSize=sizeof(SP_CLASSINSTALL_HEADER);
    p.ClassInstallHeader.InstallFunction=DIF_REMOVE; p.Scope=DI_REMOVEDEVICE_GLOBAL;
    if(!SetupDiSetClassInstallParamsW(set,&dev,&p.ClassInstallHeader,sizeof(p)) ||
       !SetupDiCallClassInstaller(DIF_REMOVE,set,&dev)) return GetLastError();
    return ERROR_SUCCESS;
}
bool belongs(IMMDevice* endpoint, const std::wstring& root) {
    ComPtr<IPropertyStore> props;
    if(FAILED(endpoint->OpenPropertyStore(STGM_READ,&props))) return false;
    PROPVARIANT v; PropVariantInit(&v);
    std::wstring id;
    if(SUCCEEDED(props->GetValue(PKEY_Device_InstanceId,&v)) && v.vt==VT_LPWSTR && v.pwszVal) id=v.pwszVal;
    PropVariantClear(&v);
    DEVINST node=0;
    if(id.empty() || CM_Locate_DevNodeW(&node,id.data(),CM_LOCATE_DEVNODE_NORMAL)!=CR_SUCCESS) return false;
    for(int depth=0;depth<16;++depth) {
        wchar_t current[MAX_DEVICE_ID_LEN]{};
        if(CM_Get_Device_IDW(node,current,MAX_DEVICE_ID_LEN,0)!=CR_SUCCESS) return false;
        if(_wcsicmp(current,root.c_str())==0) return true;
        DEVINST parent=0;
        if(CM_Get_Parent(&parent,node,0)!=CR_SUCCESS) break;
        node=parent;
    }
    return false;
}
DWORD verifyAndName(const std::wstring& root, const wchar_t* name) {
    ComPtr<IMMDeviceEnumerator> enumerator;
    HRESULT hr=CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_ALL,IID_PPV_ARGS(&enumerator));
    if(FAILED(hr)) return static_cast<DWORD>(hr);
    for(int attempt=0;attempt<100;++attempt) {
        ComPtr<IMMDeviceCollection> endpoints;
        if(SUCCEEDED(enumerator->EnumAudioEndpoints(eRender,DEVICE_STATE_ACTIVE,&endpoints))) {
            UINT count=0; endpoints->GetCount(&count);
            for(UINT i=0;i<count;++i) {
                ComPtr<IMMDevice> endpoint; endpoints->Item(i,&endpoint);
                if(!endpoint || !belongs(endpoint.Get(),root)) continue;
                ComPtr<IPropertyStore> props;
                hr=endpoint->OpenPropertyStore(STGM_READWRITE,&props);
                if(FAILED(hr)) return static_cast<DWORD>(hr);
                PROPVARIANT v; PropVariantInit(&v);
                hr=InitPropVariantFromString(name,&v);
                if(SUCCEEDED(hr)) hr=props->SetValue(PKEY_Device_FriendlyName,v);
                PropVariantClear(&v);
                if(SUCCEEDED(hr)) hr=props->Commit();
                return SUCCEEDED(hr) ? ERROR_SUCCESS : static_cast<DWORD>(hr);
            }
        }
        Sleep(100);
    }
    return ERROR_TIMEOUT;
}
}
int wmain(int argc, wchar_t** argv) {
    if(argc<3 || !validId(argv[2])) return ERROR_INVALID_PARAMETER;
    const std::wstring action=argv[1], root=instance(argv[2]);
    if(action!=L"create" && action!=L"remove") return ERROR_INVALID_PARAMETER;
    if(action==L"create" && (argc!=5 || !*argv[3] || wcslen(argv[3])>128)) return ERROR_INVALID_PARAMETER;
    DeviceSet set; set.h=SetupDiCreateDeviceInfoList(&GUID_DEVCLASS_MEDIA,nullptr);
    if(set.h==INVALID_HANDLE_VALUE) return static_cast<int>(GetLastError());
    SP_DEVINFO_DATA dev{}; dev.cbSize=sizeof(dev);
    bool exists=SetupDiOpenDeviceInfoW(set.h,root.c_str(),nullptr,0,&dev)!=FALSE;
    if(!exists && GetLastError()!=ERROR_NO_SUCH_DEVINST && GetLastError()!=ERROR_INVALID_DATA) return static_cast<int>(GetLastError());
    if(exists) { DWORD e=checkOwner(set.h,dev); if(e) return static_cast<int>(e); }
    if(action==L"remove") return exists ? static_cast<int>(removeDevice(set.h,dev)) : 0;
    wchar_t inf[MAX_PATH]{};
    const DWORD infLength=GetFullPathNameW(argv[4],MAX_PATH,inf,nullptr);
    if(!infLength || infLength>=MAX_PATH || GetFileAttributesW(inf)==INVALID_FILE_ATTRIBUTES) return ERROR_FILE_NOT_FOUND;
    // Windows verifies the package catalog/signature; no boot/security-policy changes.
    if(!SetupCopyOEMInfW(inf,nullptr,SPOST_PATH,0,nullptr,0,nullptr,nullptr)) return static_cast<int>(GetLastError());
    bool created=false;
    DWORD err=ERROR_SUCCESS;
    if(!exists) {
        if(!SetupDiCreateDeviceInfoW(set.h,root.c_str(),&GUID_DEVCLASS_MEDIA,argv[3],nullptr,0,&dev)) return static_cast<int>(GetLastError());
        if(!SetupDiSetDeviceRegistryPropertyW(set.h,&dev,SPDRP_HARDWAREID,
            reinterpret_cast<const BYTE*>(hardware),sizeof(hardware)) ||
           !SetupDiCallClassInstaller(DIF_REGISTERDEVICE,set.h,&dev)) return static_cast<int>(GetLastError());
        created=true;
    }
    SP_DEVINSTALL_PARAMS_W params{}; params.cbSize=sizeof(params);
    if(!SetupDiGetDeviceInstallParamsW(set.h,&dev,&params)) err=GetLastError();
    if(!err) {
        params.Flags|=DI_ENUMSINGLEINF; wcscpy_s(params.DriverPath,inf);
        if(!SetupDiSetDeviceInstallParamsW(set.h,&dev,&params) ||
           !SetupDiBuildDriverInfoList(set.h,&dev,SPDIT_CLASSDRIVER)) err=GetLastError();
    }
    if(!err) {
        SP_DRVINFO_DATA_W driver{}; driver.cbSize=sizeof(driver);
        BOOL reboot=FALSE;
        if(!SetupDiEnumDriverInfoW(set.h,&dev,SPDIT_CLASSDRIVER,0,&driver) ||
           !DiInstallDevice(nullptr,set.h,&dev,&driver,0,&reboot)) err=GetLastError();
        else if(reboot) err=ERROR_SUCCESS_REBOOT_REQUIRED;
        SetupDiDestroyDriverInfoList(set.h,&dev,SPDIT_CLASSDRIVER);
    }
    if(!err) {
        HRESULT com=CoInitializeEx(nullptr,COINIT_MULTITHREADED);
        if(FAILED(com)) err=static_cast<DWORD>(com);
        else { err=verifyAndName(root,argv[3]); CoUninitialize(); }
    }
    if(err && err!=ERROR_SUCCESS_REBOOT_REQUIRED && created) {
        DWORD cleanup=removeDevice(set.h,dev);
        if(cleanup) return static_cast<int>(cleanup);
    }
    return static_cast<int>(err);
}
