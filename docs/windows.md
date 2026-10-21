# Windows integration and portable build

The existing WASAPI engine, ring buffers, drift controllers and telemetry are reused. Targeted engine changes add explicit capture endpoint selection and physical-input capture. The API v2 bridge enumerates input/output endpoints and supports multiple independent capture sessions, each feeding multiple outputs; shared-mode Windows audio provides mixing. Changing destinations restarts only the affected source. ctypes loads the bundled native DLL in packaged builds.

The backend validates IDs, capture direction and layouts, prevents feedback/duplicates, isolates source failures, supports route enable/disable and restores desired routes after refresh. Its source selections include input endpoints and active output loopbacks. An output loopback is not a newly installed virtual device. Shared-mode PCM conversion and mono-to-stereo duplication may occur; bit-perfect audio and acoustic synchronization are unverified.

## Verified on Windows 11, 2026-10-20

- MSVC C++20 Release build: engine, bridge DLL, native CLI and probe compiled.
- CTest: **2/2 passed**, including real WASAPI endpoint enumeration.
- pytest: **52 passed, 4 skipped**. Linux-only integration and opt-in VM PCM tests skipped.
- PyInstaller standalone x64 GUI and console executables built with Python 3.12 and Qt Widgets.
- Both packaged offscreen and native Windows desktop startup/shutdown passed. The native backend discovered **5 devices** and loaded the bundled DLL. Read-only smoke tests started no audio routes.
- Console executable diagnostics passed. Reports and checksums are included in the portable bundle.

Windows PCM playback, physical-input capture transport, fan-out/fan-in signal integrity and acoustic synchronization remain **UNTESTED**. No virtual endpoint driver is implemented, installed or managed. A real signed driver is required; the GUI disables virtual-device creation on Windows. No system defaults or drivers were changed.

## Use and rebuild

Extract `dist/a2router-windows-x64.zip`, then launch `a2router.exe`. Python does not need to be installed. `a2router-cli.exe diagnostics` reports native capabilities and observed devices. Hiding the GUI keeps routing alive; exiting the Windows controller stops its audio engine. Console invocations cannot sustain routing after process exit.

From a Visual Studio C++ developer environment:

```powershell
powershell -ExecutionPolicy Bypass -File tools/windows/build-portable.ps1
```

The script builds/tests native targets, runs Python tests, creates GUI/console onefile executables, checks the packaged application and writes `dist/windows-x64` plus its ZIP. `-ToolchainRoot` optionally selects a locally extracted MSVC/SDK toolchain. The DLL uses a static MSVC runtime. The build script bundles runtime license notices; outputs are unsigned.

For source development, install `.[test]`, build the CMake Windows targets, and set `A2ROUTER_WASAPI_DLL` if the DLL is outside the normal build path. Missing/failed native dependencies produce errors rather than simulated routing. Linux mock tests do not establish Windows playback correctness.

## 2026-10-21 source additions (UNTESTED)

A render-only WDK driver, elevated native device manager, Python ownership/reconciliation integration and build instructions are now present under `drivers/windows/`. Earlier statements that driver source is absent describe the previous verified baseline. No new driver binary was built, signed, installed or tested. See [driver setup](../drivers/windows/README.md). Stereo 48 kHz/16-bit is the only exposed creation layout.

Synchronization now exposes a persisted additional delay of 0–10000 ms per route through the existing output FIFO and drift controller. Applying delay restarts the affected source session and all of its destinations. Native telemetry includes target/fill/capacity, applied delay, prebuffering, drift error, sample-rate adjustment and underruns. Default buffering/drift settings remain in the native engine. This is software clock adaptation and manual delay, not measured acoustic alignment. Rebuild the bridge DLL; older API-v2 DLLs without the additive delay export keep the controls disabled. This new control path is UNTESTED.
