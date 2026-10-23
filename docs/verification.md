# Verified checks for the VB-CABLE/UI revision

- Actual Windows Qt offscreen regression suite: **60 passed, 6 skipped**; tests include stable item identity/selection, retained draft edits, queued actions, native telemetry formatting, live-delay/no-restart behavior and shared-cable feedback prevention.
- Original vendor archive SHA-256 and per-file extraction integrity verified. The supplied vendor installer Authenticode status was Valid on Windows.
- Setup and uninstall source compiled successfully with Inno Setup 6.3.3 using a temporary fixture application payload. The fixture setup was never executed and is not a deliverable app build.
- Install/uninstall decisions exercised in Windows PowerShell with mocked PnP, signatures and process execution: no actual driver was installed or removed. Ownership/idempotency/removal-failure cases passed.
- Actual VB-CABLE installation/uninstallation, new native DLL compilation and physical audio playback remain UNTESTED locally; the manual workflow builds the real binaries. Temporary test dependencies/compiler are removed after verification.

Earlier records below are historical.

# Current revision: VB-CABLE and UI fixes (2026-10-23)

The custom WDK driver has been removed. A2Router now bundles the supplied VB-CABLE base package unchanged and prepares a Windows setup EXE. The package SHA-256 and its original installer Authenticode signature were checked; these are not installation or audio-transport verification. Synchronization and refresh behavior have new regression tests. Earlier results below are historical and do not establish this revision's hardware correctness.

# A2Router verification status update — 2026-10-21

New Windows virtual-driver source, root-device manager, persisted synchronization-delay controls and title/directory changes are **UNTESTED**, as requested. Only source syntax/XML parsing and diff review were performed for this revision. No driver/VM/toolchain was installed, no audio was emitted, and no automated tests or native builds were run. Historical results below do not verify these additions. Virtual-device implementation status is now UNTESTED rather than absent; only stereo 48 kHz/16-bit is exposed by the new driver.

# Development-session verification

Implemented as **A2Router (Advanced Audio Router)**. The initial checkout was clean. No existing user edits were overwritten, no Git commit/push was made, and no system audio defaults or desktop services were explicitly reconfigured. Test servers used private runtime sockets and downloaded/extracted user-local packages, without root installation.

## Latest portable Windows verification (2026-10-20)

Built on the actual Windows 11 host with MSVC and Windows SDK, through WSL interop. Native CTest **2/2 passed**; Windows pytest **52 passed, 4 skipped**. Both packaged Qt offscreen and native Windows desktop startup/shutdown passed, with real WASAPI discovery of **5 devices** and bundled native DLL loading. Console diagnostics passed. Portable files and ZIP are under `dist/`; read-only smoke reports are included. Windows PCM playback and virtual driver functionality were not verified; the driver is absent.

Latest Linux checks: pytest **50 passed, 6 skipped**, CTest **1/1 passed**, real isolated PipeWire integration **3 passed**. Earlier result counts below are historical.

## Earlier executed results

| Command | Result |
|---|---|
| `.venv/bin/python -m pip install -e '.[test]'` | Editable package built and installed |
| `.venv/bin/python -m pytest -q` | **43 passed, 3 skipped**; the 3 opt-in real-server tests are exercised separately below |
| `dbus-run-session -- .venv/bin/python tests/run_private_pipewire.py` | **3 passed**, against real PipeWire 1.0.5 / WirePlumber 0.4.17 |
| `.venv/bin/cmake -S . -B build -DCMAKE_BUILD_TYPE=Release` | Configured with GNU C++ 13.3 |
| `.venv/bin/cmake --build build -j2` | Native portable regression executable built |
| `.venv/bin/ctest --test-dir build --output-on-failure` | **1/1 passed** |
| `.venv/bin/ruff check a2router tests` | Passed |
| `.venv/bin/ruff format --check a2router tests` | Passed |
| `.venv/bin/a2router diagnostics` | Real WSLg PulseAudio compatibility server observed; 3 endpoints |
| `git diff --check` | Passed |

The Python tests cover stable discovery/classification, empty discovery, concurrent routes, fan-in/fan-out, duplicates, invalid IDs, confirmation and cycle rejection, enable/disable/removal, layout changes stopping existing audio, device reappearance, four virtual layouts, malformed configuration, wrong field types, atomic replacement failure, restoration conflicts, pending desired definitions, session locking, simulated Windows bridge behavior, CLI error handling and real Qt event-loop startup/shutdown. Linux command fixtures cover stale/reused module IDs, owned-resource cleanup, actual stream attachment validation, pactl JSON without module indices, verification failure rollback and rollback when ownership-property parsing fails.

The real PipeWire tests create application-selectable mono/stereo/5.1/7.1 sinks, including names containing both quote styles, and verify reported names/layouts. Three independent loopbacks exercise one-to-many and many-to-one concurrently. Distinct floating-point PCM channel tones are played with `pacat` and captured with `parec` from destination monitors; channel ordering and detection of two simultaneously mixed sources are checked. These tests validate signal transport, not merely module existence. A fresh controller adopts existing modules without duplication. Real Qt controls create sinks, create/disable/enable/remove a route and persist session state. A separate test restarts only the private pipewire-pulse daemon, observes pending routes, restores virtuals/routes and rechecks PCM transport.

All managed test modules are removed, temporary runtime directories are removed and private daemons are terminated. Headless daemon logs contain unavailable RTKit/libcamera/BlueZ warnings; no physical-device or realtime scheduling result is inferred from the tests. Native tests verify FIFO byte preservation over wraparound, atomic overflow rejection, silence/skip behavior, 100,000 concurrent SPSC sequence transfers and bounded drift-control arithmetic. They do not execute WASAPI.

## Capability matrix

**WORKING**: implemented and verified in a relevant real environment. **PARTIAL**: some behavior works, but important requirements or validation remain missing. **UNTESTED**: implemented but not verified in the required environment. **NOT IMPLEMENTED**: absent.

| Capability | Linux | Windows |
|---|---|---|
| Device discovery | WORKING | WORKING |
| Virtual audio devices | WORKING | UNTESTED |
| One-to-one routing | PARTIAL | UNTESTED |
| One-to-many routing | PARTIAL | UNTESTED |
| Many-to-one routing | PARTIAL | UNTESTED |
| Route enable/disable | WORKING | UNTESTED |
| Configuration persistence | WORKING | WORKING |
| Automatic restoration | WORKING | UNTESTED |
| Audio synchronization | PARTIAL | UNTESTED |
| Channel-level routing | NOT IMPLEMENTED | NOT IMPLEMENTED |
| GUI functionality | WORKING | PARTIAL |

Linux routing is marked PARTIAL because real virtual-graph routing and PCM mixing/fan-out are verified, while a physical input-to-output or virtual-to-physical listening path was unavailable. GUI WORKING refers to offscreen Qt controls driving a real PipeWire server. Discovery was observed on real WSLg and isolated PipeWire servers; exhaustive USB/Bluetooth/HDMI/surround hardware coverage is absent. Automatic restoration includes a real private pipewire-pulse restart, not every possible full PipeWire/WirePlumber/hardware failure. Native server clock adaptation is used, but independent hardware drift/acoustic alignment and adjustable route latency remain unmeasured/unexposed.

Windows engine processing is reused with explicit input/loopback capture selection added. The native bridge and portable application were compiled and tested on Windows 11. Multiple source sessions and shared-mode mixing are implemented, but Windows audio signal transport remains unverified. GUI PARTIAL means native startup/discovery/shutdown passed while full routing control verification on Windows hardware remains outstanding. No virtual endpoint driver was built, installed or tested.

## Files changed

Added:

- `.github/workflows/build.yml`
- `CMakeLists.txt`, `pyproject.toml`
- `a2router/__init__.py`, `a2router/__main__.py`, `a2router/models.py`, `a2router/controller.py`, `a2router/storage.py`, `a2router/ui.py`
- `a2router/backends/__init__.py`, `a2router/backends/base.py`, `a2router/backends/linux_pipewire.py`, `a2router/backends/windows.py`, `a2router/backends/mock.py`
- `src/PythonBridge.cpp`
- `tests/native_core.cpp`, `tests/run_private_pipewire.py`, `tests/test_cli.py`, `tests/test_core.py`, `tests/test_gui.py`, `tests/test_integration.py`, `tests/test_linux.py`, `tests/test_windows.py`
- `docs/architecture.md`, `docs/linux.md`, `docs/windows.md`, `docs/upstream-windows.md`, `docs/verification.md`

Modified: `.gitignore`, `README.md`, `build.bat`, `build_gui.bat`, `src/main_gui.cpp`. The existing GUI source change is display branding only; batch builds now use C++20 and a2router executable names.

Removed/replaced: `.github/workflows/build-multiroute-windows.yml`, whose old checkout step built the upstream repository rather than the current checkout. The replacement builds this checkout's Windows CMake targets and runs Linux checks.

Engine files extended for explicit capture selection: `src/AudioEngine.cpp`, `src/AudioEngine.h`. Retained processing components: `src/AudioRingBuffer.h`, `src/ClockDriftController.h`, `src/Logging.h`, `src/ExperimentRecorder.cpp`, `src/ExperimentRecorder.h`. Their portable components were tested on Linux. `.venv/`, downloaded packages, generated binaries and caches are ignored development artifacts.

## Remaining work

1. Verify real microphone, speaker, headphone, HDMI and Bluetooth routes on a native desktop, including disconnect/reconnect under playback and default-device policy behavior.
2. Build/run the WASAPI DLL on Windows and test enumeration, fan-out, partial startup failures, source/default changes, telemetry and shutdown with real endpoints.
3. Measure physical latency/drift and underruns before exposing any additional synchronization controls or making alignment guarantees.
4. Improve Windows input support and per-output live updates; build a real signed virtual driver only as a separate, explicitly tested project.
5. Add optional channel-level routing after device-level hardware tests are stable. It remains disabled today.

Reproducible installation, launch, diagnostic, native build and test commands are in the root README and platform documents. No claim of production readiness, bit-perfect hardware playback or sample-accurate synchronization is made.

Portable additions: `a2router/portable.py`, `tools/windows/build-portable.ps1`, `tools/windows/portable_entry.py`, `tools/windows/collect_licenses.py`, `tools/windows/PORTABLE.txt`, `tests/test_portable.py`, `tests/test_windows_native.py`, and `tests/windows_probe.cpp`. See Git status for the complete uncommitted implementation.
