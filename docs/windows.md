# Windows

A2Router is a portable x64 application. Extract the entire ZIP and launch `a2router.exe`; no app installer, Python installation or WDK is needed on the target machine. Build instructions are in the [README](../README.md). GitHub Actions are manual-only and produce one GUI application and its portable ZIP. No console executables are distributed.

## Virtual cable

The Virtual devices page installs the original VB-CABLE package only after **Create output** is clicked. Existing endpoints are reused. The driver helper checks its Authenticode signature, waits for vendor setup and checks PnP. The backend refreshes until an active endpoint appears. Ready endpoints can be used immediately; pending restart or missing endpoints are reported. No forced restart occurs.

One base cable is included. Its playback alternatives share transport; they are not independent named cables. Detection follows the audio endpoint's topology to its adapter and checks the actual vendor service, with exact `VB-Audio Virtual Cable` / `VB-Audio Point` adapter names as fallbacks. The supplied INF confirms those names. User-editable endpoint names are not used as identities.

Select an endpoint in Virtual devices and **Scan formats**. Exact `IAudioClient::IsFormatSupported` exclusive-format probes provide candidate 1/2/4/6/8/16-channel PCM/float formats; unavailable combinations are omitted. The GUI exposes channel count, bit depth/sample rate and the uncompressed PCM transport rate. **Apply format** refuses active managed routes, requests the selected Windows shared default format, verifies it and restores/verifies the previous format on failure. Playback and recording endpoints must each be configured as needed. Changes affect other apps using that endpoint too.

Windows exposes no documented shared-default-format setter. `src/WindowsEndpointControl.h` isolates the known `IPolicyConfig` compatibility interface's first four methods; unsupported interfaces return a clear error and **Windows Sound…** remains available. No default-device selection API or registry patch is used. Compatibility must be tested on target Windows versions. The [public interface reference](https://github.com/frgnca/AudioDeviceCmdlets/blob/master/SOURCE/IPolicyConfig.cs) documents the known method order; this is not a Microsoft stability guarantee.

**Rename in Windows** writes `PKEY_Device_FriendlyName`, commits and verifies it. The native code attempts rollback on failure. If administrator access is required, the frozen GUI requests UAC and runs an internal rename-only child of the same portable executable; it does not install a driver, load a profile or start routes. The parent verifies the new name by discovery. Stable endpoint IDs and route definitions remain intact.

**Remove driver…** requires confirmation and removal of dependent routes. It invokes the original vendor uninstaller, verifies removal/pending restart and reports failure. Removing the portable application folder does not uninstall the shared driver. No driver operation runs on startup, refresh, profile restoration, tests or CI.

## Routing and synchronization

Each native source owns the existing MultiRoute engine. Standard routes keep the original format path; Windows mixes independent source streams. VB-CABLE recording endpoints are captured as inputs; physical render monitors use loopback. Stable PnP service discovery identifies cable endpoints and feedback groups.

Optional channel maps use `{source, destination, gain}` entries with zero-based channel indices and finite linear gains from −4 to +4 in configuration. The GUI exposes −60 to +12 dB. The native immutable sparse matrix decodes float32/PCM16/24/32, accumulates in double precision, duplicates/sums selected channels and clamps output to ±1. Unmapped outputs are silent. The destination's active channel count/mask is used with source-rate float32. Conversion/resampling can occur in shared-mode WASAPI. Unsupported source formats or invalid indices fail explicitly. Native callbacks allocate no buffers or matrices per audio block.

The per-output FIFO and drift controllers retain source-format units, including on mapped outputs. Synchronization shows available buffer/target, rate correction, underruns and clipped-sample counts. Delay drafts persist through polling until Apply/Discard. Supported live delays update the native buffer without a source restart; the restart fallback needs explicit permission. Acoustic alignment and bit-perfect hardware playback are not claimed.

## Verification

Linux Qt tests, native matrix sample tests and Windows control/PowerShell simulations were run for this revision. Windows testing used existing Python/PowerShell with tests shared from Linux: no Windows packages, tools or drivers were installed. No Windows compiler was available, so the updated bridge/portable EXE must be built by the manual workflow and tested on a suitable Windows target. Driver install/removal and audible playback were not exercised.

## Mixer and routing workspace

Native `IAudioEndpointVolume` provides master volume/mute and `IAudioMeterInformation` provides observed peaks for physical inputs, outputs and actual cable capture/playback endpoints. Generated loopback aliases are excluded from duplicate mixer controls. Fast meter polling is serialized off the GUI thread and only runs while Audio is visible. Charts retain stable device identity, avoid interpolating across gaps and show unavailable data explicitly. Volume control does not restart source sessions.

The top navigation and manual synchronization workflow are documented in [the user guide](user-guide.md). Rename verification now reacquires endpoint/property-store instances; write/commit access-denied HRESULTs reach the explicit elevation flow. A rejected unchanged write does not attempt rollback. This change still requires a target-machine Windows DLL build and rename check.

## Current UI and packages

Endpoint renaming is no longer exposed; Windows/vendor names are retained. Device/virtual configuration is combined. VB-CABLE routed gain uses the new native stream-control extension and actual WASAPI readback. Calibration uses finite native capture/playback and offline analysis; target Windows build/hardware checks remain required. The manual workflow now produces portable and optional single-file setup outputs; driver install/remove choices are unchecked. See [current guide](user-guide.md).

Application capture uses Windows SDK process-loopback types (SDK 20348+; CI uses
26100) and links Mmdevapi. Runtime support is checked with the real OS build.
Public application/live-matrix extensions are version 1, additive to bridge ABI 2.
Process creation times prevent a recycled PID being treated as the old source.
No endpoint driver is required for process capture. CI compilation and real
hardware validation of these new native paths remain required in this environment.

## SDK GUID include order

The bridge includes COM GUID declarations (`cguid.h`/`objbase.h`) before the
audio headers. Kernel Streaming headers define `GUID_NULL` through `__uuidof`;
loading `cguid.h` afterwards can expand that macro inside its GUID declaration
and cause C2059 on SDK 26100. Keep `initguid.h` first to retain the SDK property-key
definitions needed by the bridge. Reference: Microsoft's
[KS header](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/shared/ks.h)
and [COM GUID declarations](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/cguid.h).
