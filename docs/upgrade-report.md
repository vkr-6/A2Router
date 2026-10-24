# Workspace upgrade report

This revision implements the first professional-workspace upgrade around the
existing engine. It is not a production-readiness or full master-prompt completion
claim. Acoustic calibration is deferred at the user's request.

## Changes

- Compact horizontal icon-over-caption navigation, traditional menus and shortcuts.
- Full-width sortable/filterable model/view endpoint tables, column controls,
  CSV/copy operations and constrained volume/mute editors.
- Routing tabs, splitter layout, embedded delay controls, native route monitor,
  existing endpoint Mixer, virtual-device controls and diagnostics export.
- Dynamic channel grid with connection toggles, bulk gains, explicit presets and
  existing-route edits. Backend validation/rollback protects the previous map.
- Profile New/Open/Save/Save As and recent selection. GUI replacement validates
  before changing routes and attempts route rollback on unexpected failure.
- A separate transport gate preserves desired enabled states on GUI Stop; refresh
  does not restart stopped routes. CLI start/stop/load semantics remain compatible.
- System/Light/Dark themes, density selection, separate QSettings layout persistence.
- Endpoint rename readback uses fresh stores and bounded retries. Access-denied
  writes/commits reach the existing portable elevation flow. Rejected unchanged
  writes no longer attempt a failing rollback. Native helper regression tests
  cover denial, delayed observation, unreadable baseline and verified rollback.
- MIT license for original A2Router contributions, with explicit upstream/vendor
  exclusions; license files are included in source and portable packaging.

No real-time processing was moved into Python. No driver payload was modified.
No Windows package, compiler or driver was installed; no Windows endpoint name,
format, volume or system default was changed during validation.

## Validation

- Linux Python/Qt offscreen: **108 passed, 13 skipped** (`python -m pytest -q`).
  Skips: seven Windows-only helper tests, three opt-in PipeWire cases and three
  opt-in native Windows cases.
- Existing Windows Python/PowerShell: **74 passed** in selected core, backend,
  matrix, endpoint-control, vendor and helper tests. Audio APIs/installer operations
  were simulated. One cache-write permission warning occurred; it did not affect
  tests, and source ownership is restored for handoff.
- CMake/GNU C++20 build and CTest: **1/1 passed**. Strict direct native build with
  `-Wall -Wextra -Werror` also passed. These include known-PCM matrix, ring-buffer,
  SPSC, drift-controller and rename-transaction tests, not WASAPI hardware tests.
- Ruff check and format checks passed; `git diff --check` passed.
- Qt offscreen 1366×768 layout smoke passed at scale factors 1, 1.25, 1.5 and 2,
  reporting corresponding DPRs. This is not a Windows multi-monitor/DPI test.
- Existing Windows PowerShell parsed the portable build script successfully using
  the parser API. Script execution policy was not changed.
- Vendor ZIP SHA-256 remains
  `b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb`.

This environment has no MSVC/Windows SDK compiler or native PipeWire utilities.
The updated Windows bridge was not compiled here; no new portable EXE/ZIP was
produced. Use the existing **manual-only** GitHub Actions workflow. On success its
outputs are `dist/windows-x64/a2router.exe` and `dist/a2router-windows-x64.zip`.
The previously fixed `PKEY_AudioEngine_DeviceFormat` linkage and this rename change
both require the workflow's Windows DLL build and target-machine verification.

## Support matrix for this revision

Working means verified within the stated scope. Requires Hardware Test includes
operations needing target-platform/native audio validation.

| Feature | Linux | Windows |
|---|---|---|
| Compact UI, menus and themes | Working (Qt offscreen) | Requires Hardware Test |
| Device discovery | Requires Hardware Test (mock regression passes; real server unavailable today) | Requires Hardware Test |
| Virtual devices | Requires Hardware Test | Requires Hardware Test; one shared VB-CABLE base installation |
| One-to-one / fan-out / many-to-one | Requires Hardware Test | Requires Hardware Test |
| Enable/disable and transport stop | Working in control tests; real server check remains | Working in control tests; native check remains |
| Profiles, atomic persistence | Working | Working (selected control tests) |
| Reconnect recovery | Partial | Requires Hardware Test |
| Channel matrix sample processing | Unsupported by Linux routing backend | Requires Hardware Test; shared C++ sample tests pass |
| Endpoint volume/mute | Requires Hardware Test | Requires Hardware Test |
| Endpoint rename/format | Unsupported in this backend | Requires Hardware Test |
| Manual route delay | Unsupported | Requires Hardware Test |
| Clock adaptation | Partial (OS supplied) | Requires Hardware Test; native controller unit tests pass |
| Acoustic calibration | Unsupported; deferred | Unsupported; deferred |
| EQ/compressor/test-tone/app capture/global hotkeys | Unsupported | Unsupported |

## Screenshots

Actual Qt screenshots using a labelled simulated backend; no measured audio is
invented. Simulated delay support and the eight-channel example are test-only.

- [Light workspace](images/studio-light.png)
- [Dark workspace](images/studio-dark.png)
- [Integrated delay controls](images/studio-delay.png)
- [Eight-channel matrix](images/studio-matrix.png)
- [Endpoint mixer](images/studio-mixer.png)

## Remaining work

Finish native Windows build verification, then test real rename/elevation, channel
playback/order, endpoint controls, delay updates, stop/reconnect behavior and driver
lifecycle on a suitable Windows target. Acoustic calibration needs native signal
playback/capture, microphone validation, cancellation/state restoration and real
measurement validation. It currently has no measurement implementation.

Further power-user work includes per-stream mute/solo/faders, route labels/groups,
undo/redo, test signals, application capture, sub-millisecond delay APIs and expanded
DSP. Emergency Mute is a serialized managed-transport stop and can wait behind an
active control operation; it is not a real-time hardware panic switch. UI settings
use per-user QSettings even though application distribution is portable. Virtual
devices omitted from a newly opened profile are retained for ownership safety.

See [user guide](user-guide.md), [build/test commands](testing.md),
[project description](project-description.md) and [license scope](../LICENSING.md).

## Files changed

Added:

- `LICENSE`
- `LICENSING.md`
- `a2router/matrix_ui.py`
- `a2router/studio.py`
- `a2router/tables.py`
- `docs/images/studio-dark.png`
- `docs/images/studio-delay.png`
- `docs/images/studio-light.png`
- `docs/images/studio-matrix.png`
- `docs/images/studio-mixer.png`
- `docs/project-description.md`
- `docs/upgrade-report.md`
- `docs/user-guide.md`
- `src/EndpointRename.h`
- `tests/conftest.py`
- `tests/test_studio.py`

Modified:

- `MANIFEST.in`
- `README.md`
- `THIRD_PARTY_NOTICES.md`
- `a2router/backends/base.py`
- `a2router/backends/windows.py`
- `a2router/controller.py`
- `a2router/dashboard.py`
- `a2router/ui.py`
- `docs/architecture.md`
- `docs/verification.md`
- `docs/windows.md`
- `src/PythonBridge.cpp`
- `tests/native_core.cpp`
- `tests/test_device_controls.py`
- `tests/test_gui.py`
- `tests/test_windows.py`
- `tools/windows/PORTABLE.txt`
- `tools/windows/build-portable.ps1`
