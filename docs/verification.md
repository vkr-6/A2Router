# Audio console / native endpoint controls revision

Executed checks for the current source revision:

- Linux Python/Qt offscreen: **91 passed, 13 skipped**. Tests cover standard routing, 16-channel configuration UI, adapter classification, system rename wiring, real-data graph handling, sound controls, filtering, profiles, cable feedback and on-demand-install simulations.
- Existing Windows Python 3.12 / PowerShell, using test dependencies shared from Linux: **72 passed** in the selected core, Windows control, device-configuration, matrix, vendor and driver-helper suites. Installer commands were mocked. Nothing was installed on Windows.
- GNU C++20 / CMake / CTest: **1/1 passed**. Native sample checks include float identity, channel swaps/duplication, unmapped silence, double-precision summing/clipping, finite-sample protection and PCM16/24/32 decoding. Existing ring-buffer/SPSC/drift checks remain included.
- Ruff check and formatting passed. SVG-to-multisize-ICO generation passed using Qt on Linux.

No existing Windows compiler was found. The updated native WASAPI bridge and complete portable EXEs have **not** been rebuilt in this session. The manual GitHub workflow builds one GUI executable, checks the control/configuration/matrix exports and packages the icon/theme/vendor files. It does not distribute CLI or native console executables. Driver installation/removal, native endpoint rename/format policy, real Windows meters/volume, channel-matrix playback and hardware synchronization remain unverified. No real driver installer, audio playback, Windows package installer or VM was run.

## Capability scope

**WORKING** means implemented and verified in a relevant real environment; **PARTIAL** means important requirements remain; **UNTESTED** means implemented but not verified in the required environment; **NOT IMPLEMENTED** means absent.

| Capability | Linux | Windows |
|---|---|---|
| Device discovery | WORKING (earlier private PipeWire checks) | UNTESTED for updated bridge |
| Virtual audio devices | WORKING (earlier private PipeWire checks) | UNTESTED (one shared vendor cable) |
| One-to-one routing | WORKING (earlier private PipeWire graph) | UNTESTED for updated bridge |
| One-to-many routing | WORKING (earlier private PipeWire graph) | UNTESTED for updated bridge |
| Many-to-one routing | WORKING (earlier private PipeWire graph) | UNTESTED for updated bridge |
| Route enable/disable | WORKING (earlier private PipeWire graph) | UNTESTED for updated bridge |
| Configuration persistence | WORKING | WORKING (control tests) |
| Automatic restoration | PARTIAL (hardware reconnection unmeasured) | UNTESTED (control simulations pass) |
| Audio synchronization | PARTIAL (server-managed; acoustic alignment unmeasured) | UNTESTED |
| Channel-level routing | NOT IMPLEMENTED | UNTESTED (native matrix samples pass on Linux) |
| GUI functionality | WORKING (Qt offscreen; backend simulations) | UNTESTED for this UI revision |

Earlier sessions verified a Windows build, real endpoint discovery and packaged Qt startup, and three isolated Linux PipeWire integration cases. Those results predate this native matrix/portable lifecycle revision. They do not prove current Windows playback, driver correctness, bit-perfect transport or acoustic alignment.

## Environment observation

A read-only query of the existing Windows host reported `VB-Audio Virtual Cable`, `ConfigManagerErrorCode=10` and `Status=Error`. No installation, repair, format/name change or audio playback was attempted. This observation does not diagnose the user's separate working target. Control tests used simulated native APIs; it is not evidence that this host's cable can play audio.

UI previews under `docs/images/` are captured from the actual Qt application with labelled simulated backends. Reference layout ideas were reviewed from the official EarTrumpet and RME TotalMix pages; no assets or UI code were copied.
