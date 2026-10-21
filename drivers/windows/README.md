# A2Router Windows virtual output driver

Status: **UNTESTED**. Source implementation only; no signed driver binary is included. No Windows build, driver deployment or audio tests were executed for this change, at the user's request.

This project vendors Microsoft's minimal WaveRT `SimpleAudioSample` driver at the pinned revision recorded in `a2router/UPSTREAM.md`, with its MS-PL license and original copyright notices. It exposes a genuine Windows render endpoint through PortCls. It is not a Python-only device or an app-local list entry.

Local adaptations:

- Own `A2RouterAudio` service, binary and catalog names, independent of the upstream sample.
- Own hardware ID `ROOT\A2RouterAudio`; owned instances `ROOT\A2ROUTER\<UUID without dashes>`.
- Render-only endpoint. Synthetic microphone registration and the sample's tone-generating capture endpoint are not installed.
- Debug audio recording and its process-global worker setup are disabled. Adapter singleton restriction is removed so each created root instance can own an independent render endpoint.
- No hardware loopback pin: Windows shared-mode software loopback is the intended capture path for routing rendered audio through the existing engine. Signal transport has not been verified.
- Initially **stereo, 48,000 Hz, 16-bit PCM** only, matching the actual native format table. Mono/surround options remain unavailable on this driver.
- INF targets Windows 10 build 19041 and later; OS/WDK compatibility remains unverified.

## Build on Windows

Install Visual Studio C++ Build Tools, matching Windows SDK/WDK, and the WDK Visual Studio extension. In a developer PowerShell from the A2Router project root:

```powershell
powershell -ExecutionPolicy Bypass -File tools/windows/build-driver.ps1
cmake -S . -B build -A x64
cmake --build build --config Release
```

The driver script copies source to ignored `build/windows-driver/source/` before building. It writes `A2RouterAudio.inf`, `.sys`, `.cat` and the Microsoft license to `build/windows-driver/package/`. A normal application-only build does not require WDK. Never edit the INF after its catalog is signed.

The default driver build is unsigned. Production Windows requires Microsoft-accepted driver signing. For a separately prepared development machine, a test-signed package may be used according to Microsoft's driver deployment guidance. The script deliberately does not change boot security, enable test signing, generate/import certificates, or install a driver. Optional `-CertificateThumbprint` selects an existing WDK test-signing certificate; it does not make a test signature production-valid.

## Create devices

Place a valid signed package in `build/windows-driver/package/`, or set `A2ROUTER_DRIVER_INF` to its INF. Rebuild both the WASAPI DLL and `a2router_device_manager.exe`. Launch the GUI, open Virtual devices, enter a name and create a stereo output. The controller requests UAC elevation for the native helper; ordinary routing remains unelevated. Windows checks package acceptance during installation. A missing package/helper leaves creation disabled with a setup explanation.

The helper creates a deterministic root devnode, binds only that node to the INF, waits for an active MMDevice endpoint and sets its Windows friendly name. It rolls back a newly created node on installation/endpoint verification failure; a restart-required result is reported separately. It never sets default speakers or microphones. Device removal only targets the exact A2Router-owned instance and hardware ID, and refuses while managed routes depend on it. Removing one device does not remove the shared driver package or other instances.

The endpoint appears to other compatible Windows applications after successful installation. Select it as their output, then select its monitor in A2Router and add physical-output routes. Device definitions retain stable application IDs across restarts; native endpoint IDs are resolved from actual device ancestry.

For portable packaging, build the driver package first, then run `tools/windows/build-portable.ps1`. The helper is bundled; the optional package is copied beside the EXE in `driver/`. A portable EXE alone cannot replace a kernel driver or bypass Windows signing policy. Inspect `%WINDIR%\inf\setupapi.dev.log` if Windows rejects installation.

Official references:

- https://github.com/microsoft/Windows-driver-samples/tree/bb68ed5e770bce04dc5395ec9258dafab034184d/audio/simpleaudiosample
- https://learn.microsoft.com/windows-hardware/drivers/install/driver-signing

## GitHub Actions

The main workflow runs only through **Actions → A2Router build → Run workflow**, with an optional `build_driver` input. Pushes and pull requests do not start it. It restores matching WDK/SDK NuGet packages pinned to `10.0.26100.6584` and uploads `A2Router-driver-x64-UNSIGNED`. The driver package is separate from the portable application artifact. Local NuGet builds use `tools/windows/build-driver.ps1 -UseNuGet` with a Visual Studio developer shell and NuGet CLI. These workflow changes have not been dispatched here. An unsigned CI output is not ready for installation on a normal Windows system.

NuGet builds explicitly resolve host-compatible StampInf, Inf2Cat and SignTool directories from the pinned packages before starting MSBuild. `StampInfToolPath` and `Inf2CatToolPath` are passed as MSBuild properties, and the tool directories are temporarily added to PATH. Tool selection follows the build host architecture, independently of the driver target; this accommodates the kit's x86-only Inf2Cat. The original PATH is restored after the build. Missing tools now fail with their expected package location instead of a later TRK0005 error.
