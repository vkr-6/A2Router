# Windows

A2Router is a portable x64 application. Extract the entire ZIP and launch `a2router.exe`; no app installer, Python installation or WDK is needed on the target machine. Build instructions are in the [README](../README.md). GitHub Actions are manual-only and produce GUI, CLI and native artifacts.

## Virtual cable

The Virtual devices page installs the original VB-CABLE package only after **Create output** is clicked. Existing endpoints are reused. The driver helper checks its Authenticode signature, waits for vendor setup and checks PnP. The backend refreshes until an active endpoint appears. Ready endpoints can be used immediately; pending restart or missing endpoints are reported. No forced restart occurs.

One base cable is included. Its playback alternatives share the same transport; A2Router never pretends they are independent named cables. The name field creates a persisted A2Router display alias. **Configure channels / Windows name…** opens Windows Sound, which controls the actual system name, speaker layout and default format. A2Router displays the reported result instead of writing undocumented endpoint policy/registry settings.

**Remove driver…** requires confirmation and removal of dependent routes. It invokes the original vendor uninstaller, verifies removal/pending restart and reports failure. Removing the portable application folder does not uninstall the shared driver. No driver operation runs on startup, refresh, profile restoration, tests or CI.

## Routing and synchronization

Each native source owns the existing MultiRoute engine. Standard routes keep the original format path; Windows mixes independent source streams. VB-CABLE recording endpoints are captured as inputs; physical render monitors use loopback. Stable PnP service discovery identifies cable endpoints and feedback groups.

Optional channel maps use `{source, destination, gain}` entries with zero-based channel indices and finite linear gains from −4 to +4 in configuration. The GUI exposes −60 to +12 dB. The native immutable sparse matrix decodes float32/PCM16/24/32, accumulates in double precision, duplicates/sums selected channels and clamps output to ±1. Unmapped outputs are silent. The destination's active channel count/mask is used with source-rate float32. Conversion/resampling can occur in shared-mode WASAPI. Unsupported source formats or invalid indices fail explicitly. Native callbacks allocate no buffers or matrices per audio block.

The per-output FIFO and drift controllers retain source-format units, including on mapped outputs. Synchronization shows available buffer/target, rate correction, underruns and clipped-sample counts. Delay drafts persist through polling until Apply/Discard. Supported live delays update the native buffer without a source restart; the restart fallback needs explicit permission. Acoustic alignment and bit-perfect hardware playback are not claimed.

## Verification

Linux Qt tests, native matrix sample tests and Windows control/PowerShell simulations were run for this revision. Windows testing used existing Python/PowerShell with tests shared from Linux: no Windows packages, tools or drivers were installed. No Windows compiler was available, so the updated bridge/portable EXE must be built by the manual workflow and tested on a suitable Windows target. Driver install/removal and audible playback were not exercised.
