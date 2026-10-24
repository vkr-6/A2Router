# Clean UI, calibration and packaging report

## Implemented

- Routing contains endpoint selectors/configured routes and optional Channel Matrix
  and delay controls. Showcase inventories, informational processing/monitor pages
  and profile controls outside File are removed.
- Physical/virtual Devices share one workspace with exact format configuration.
  Vendor/Windows names are retained. Shared VB-CABLE pins are grouped as one cable;
  Mixer has one cable strip and compact six-pixel level meters.
- Cable gain/mute uses native per-stream volume, with WASAPI readback, startup-gain
  initialization, profile persistence and rollback. Nonunity/muted startup rejects
  an unavailable verified gain service rather than playing at full volume.
- Explicit normalized stereo/mono downmix and stereo-to-surround expansion presets.
  Mapping follows reported positions. LFE is excluded, upmix does not recover
  discrete surround, and unsupported/unknown layouts are rejected.
- Native Windows chirp playback and timestamped microphone capture; offline FFT
  matched filtering, noise/clipping/reflection checks, multipass outlier rejection,
  quality/spread and relative compensation. Review precedes Apply. Cancellation,
  failure restoration, emergency suppression of playback restoration, profile
  metadata and JSON export are implemented.
- White/Dark/Lime/Blue/Violet/System themes and adapted vector A-squared branding.
- Manual-only workflow inputs independently select Windows portable/setup and Linux
  artifacts. Setup embeds the portable app/vendor payload; shortcuts/launch have
  choices and driver installation/removal are unchecked by default. The validated
  vendor helper is reused. No driver installer runs during CI packaging.
- Linux runtime freezing, tar.gz/.deb, desktop launcher, runtime notices and checksums.
  Frozen pactl processes use the host library environment.

## Executed validation

- Full Linux Python/Qt suite: **141 passed, 13 skipped**.
- Selected tests using existing Windows Python/PowerShell: **80 passed**. These are
  control/helper/native-API simulations, not hardware playback or calibration.
- Native GNU C++20/CMake/CTest: **1/1 passed**, including PCM matrix, chirp/encoding,
  ring/SPSC/clock and rename-transaction regressions. Windows-only source was not
  compiled with MSVC here.
- Ruff check/format passed. Windows PowerShell parsed both build scripts.
- Actual Linux PyInstaller freeze succeeded. The frozen application's read-only
  mock GUI startup/shutdown and synthetic NumPy FFT runtime check passed.
- Real .deb/tar packaging and checksum generation succeeded; packages were not
  installed. Packaging tests also validate paths/metadata using a dummy executable.
- Screenshots come from actual Qt with an explicitly labelled simulated native API;
  synthetic microphone recordings are used only for testing/preview, not production.

The local host lacks the Windows compiler/SDK and Inno Setup compiler. New Windows
DLL/portable/setup binaries remain unbuilt locally and need the manual workflow.
No Windows software/driver was installed and no Windows audio settings were changed.
There is no local PipeWire service/hardware validation in this revision. Missing host
XCB libraries produced freeze warnings; they are runtime dependencies declared by
the Linux package/instructions. Offscreen startup passed.

## Generated artifacts

- `dist/a2router-linux-x86_64.tar.gz` (approximately 73 MB).
- `dist/a2router_0.1.0_amd64.deb` (approximately 56 MB).
- `dist/SHA256SUMS-linux.txt`.
- `build/linux-freeze/a2router/packaged-smoke.json`.

Local Linux binaries were built on Ubuntu 24.04/glibc 2.39. The workflow builds on
Ubuntu 22.04 for that runner's compatibility baseline. Windows workflow outputs are
`dist/a2router-windows-x64.zip` and `dist/a2router-windows-x64-setup.exe` when those
jobs pass. Windows output generation has not been verified in this session.

## Support scope

| Capability | Linux | Windows |
|---|---|---|
| Clean GUI/themes | Working offscreen | Requires Hardware Test |
| Actual packaged startup | Working offscreen, mock backend | Requires Hardware Test |
| Routing/device discovery | Partial: preserved, simulated regressions pass; server unavailable locally | Requires Hardware Test |
| Virtual devices | Partial: PipeWire backend preserved | Requires Hardware Test; shared base cable only |
| Volume/mute | Partial: endpoint control backend preserved | Requires Hardware Test; new stream path implemented |
| Channel conversion | Unsupported by Linux routing backend | Requires Hardware Test; coefficient/PCM tests pass |
| Manual delays/drift | Partial: OS management, no manual delay API | Requires Hardware Test |
| Acoustic calibration | Unsupported | Requires Hardware Test; native capture/playback implemented, algorithms/lifecycle tested synthetically |
| Profiles/persistence | Working in tests | Working in selected control tests |
| Portable package | Working packaging/offscreen scope | Requires Hardware Test |
| Installer | Working .deb generation; not installed | Requires Hardware Test; Inno compilation/execution pending |

Calibration is an estimate of matched arrival relative to a software-start/QPC
reference, not sample-perfect or separated acoustic/transport/driver latency.
It tests the first playback channel and requires quiet surroundings and a fixed
microphone. Native delay requests use integer ms. Ordinary Emergency Mute is a
serialized managed-transport stop; during calibration it also requests lock-free
native cancellation. No bit-perfect, production-readiness or hardware-sync claim.

## Screenshots and instructions

[Routing](images/clean-routing.png), [Mixer](images/clean-mixer.png),
[Devices](images/clean-devices.png), [Calibration](images/clean-calibration.png),
[White](images/clean-white.png), [Blue](images/clean-blue.png).

See [README](../README.md), [user guide](user-guide.md), [license scope](../LICENSING.md)
and [project description](project-description.md). Highest-value next check: run
Windows CI, then test actual stream gain, microphone calibration, delay application,
format changes, and optional setup/uninstall driver flows on a suitable target.
