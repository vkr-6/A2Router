# Verification

Current scope: [clean UI/calibration/packaging report](upgrade-report.md).

- Linux Python/Qt: 141 passed, 13 skipped.
- Selected existing Windows Python/PowerShell control/helper tests: 80 passed.
- Native CTest: 1/1 passed on Linux.
- Frozen Linux GUI and offline synthetic FFT runtime checks passed.
- Linux tar.gz/.deb built; neither package installed.
- Windows portable/setup build scripts parsed; Windows native/setup compilation
  and acoustic hardware verification remain pending.

Simulations and synthetic recordings are clearly separated from real native audio
claims. No Windows software or driver was installed during this revision.

CI launcher fixes (2026-10-24):

- Windows staging now includes `.github`, required by the workflow packaging test.
- Private PipeWire tests clear inherited `PULSE_RUNTIME_PATH` and create the
  standard private `pulse` directory before starting daemons, avoiding the
  reported nested `pulse/pulse` startup failure.
- Targeted packaging/environment regressions: 6 passed; Ruff check/format passed.
- Full Windows packaging and live PipeWire execution require a CI rerun;
  the local environment has no PipeWire daemons. RTKit warnings are separate
  from the fatal socket-directory error and do not require elevated audio setup.

Linux property-parser fix (2026-10-24):

- Reproduced corrupted nested `device.description` and ownership properties on
  real PipeWire 0.3.48, using extracted Ubuntu 22.04 packages in a private session.
- Legacy creation now passes the description as a separately quoted top-level
  property and keeps ownership tags in a simple proplist. Verification and
  cleanup checks remain enabled.
- On 0.3.48, names containing both quote types or backslashes are rejected before
  allocation with an upgrade/simpler-name explanation; names with spaces or
  either quote type retain their exact text. Modern quoting is unchanged.
- `dbus-run-session -- python tests/run_private_pipewire.py`: 3 passed on
  PipeWire 0.3.48 and 3 passed on PipeWire 1.0.5 (temporary extracted runtimes).
  Includes mono/stereo/5.1/7.1, real PCM fan-out/mixing, GUI operations, server
  restart restoration, ownership and cleanup. No physical playback was tested.
- Full Python suite: 150 passed, 13 skipped. Ruff check/format passed.
- No audio service, Windows software or driver was installed; all private
  daemons and managed test resources were cleaned up by the harness.

Windows controls and matrix fixes (2026-10-29):

- Gain confirmation now waits up to 600 ms for the native supervisor's periodic
  telemetry publication. The native synchronous WASAPI verification and rollback
  paths remain in place; volume edits do not restart routes.
- Acoustic capture accepts silent ambient samples before the chirp, retaining
  the loud-input guard. A completely silent recording is rejected after the test
  signal; timestamp, discontinuity and analysis-quality checks remain enabled.
  Repeated identical per-pass errors are shown once.
- Channel Matrix now has synchronized source/output selectors and refreshes when
  formats change or channel information becomes unavailable. Saved endpoint
  formats are distinguished from the active mix format; a pending change no
  longer reports unconditional success or invents additional active channels.
- Linux verification: full Python/Qt suite 154 passed, 13 skipped; focused
  device controls/calibration/GUI tests 46 passed; Ruff check/format passed.
  GNU C++20 build and execution of tests/native_core.cpp passed (PCM integrity,
  channel operations, queues, concurrency and drift controller checks).
- Windows backend tests use simulated native APIs. Windows calibration capture
  changes require a rebuilt DLL and Windows hardware verification; Bluetooth
  microphone/playback behavior was not measured. No Windows software was installed.

Failure-path audit (2026-10-29):

- Disabled-route reconciliation now disconnects residual resources even while
  global transport is running.
- Failed profile replacement stops resources created by the replacement before
  restoring previous routes. If cleanup fails, transport recovery is suspended
  and resource identities remain visible for a cleanup retry.
- Calibration no longer clears an existing emergency-stop latch. Explicit Start
  is required before another measurement can begin.
- Windows refresh-time gain reconciliation uses the same bounded telemetry wait
  as direct volume edits, avoiding a second supervisor-snapshot race.
- Virtual-device definitions and route boolean flags now produce structured
  errors before allocation. Atomic JSON writes reject non-finite/unserializable
  values and wrap directory-creation errors, preserving existing files.
- Verification: full Linux Python/Qt suite 168 passed, 13 skipped; 13 dedicated
  failure-path regressions passed; Ruff check/format and git diff checks passed.
  Windows API behavior is simulated in these tests; no Windows software or
  driver was installed. Real PipeWire and Windows hardware suites remain opt-in
  and were not run in this audit. This is a scoped audit, not proof of zero bugs.

Monitoring confirmation, capture settling and transparent branding (2026-10-29):

- Added explicit Yes/No route monitoring confirmation with No as default; accepted
  consent is persisted on the route. Backend feedback protections remain active.
- Discarded startup capture packets for 250 ms before the 450 ms chirp onset.
  Subsequent timing errors/discontinuities still reject measurements. Ambient
  loudness checking now waits for actual retained samples rather than an elapsed
  startup timer. This native WASAPI change requires Windows hardware retesting.
- Replaced icon and wordmark backgrounds with a simple original blue SVG mark.
  Existing GUI, Windows EXE/setup ICO generation, Linux desktop packaging and
  README reference these source assets. Old binaries must be rebuilt.
- Full Linux Python/Qt suite: 169 passed, 13 skipped. Ruff check/format passed.
  Both SVGs rendered through Qt with transparent corners verified; Windows ICO
  generated on Linux. No Windows installation or hardware test was performed.

Branding, volume scope, conversion levels and Linux latency (2026-11-01):

- Recreated the supplied logo.jpeg design as clean white/orange vector source
  assets, with transparent backgrounds. Qt SVG rendering and Windows ICO
  generation passed on Linux; the prior raster cutout attempts were discarded.
- Windows Mixer now distinguishes routed playback gain from the Windows cable
  playback endpoint. Endpoint mode observes external changes without changing
  route gain. The official VB-CABLE control panel is hash-verified before launch;
  this action does not run setup or modify driver settings.
- The vendor's reference manual documents that Windows Volume Control must be
  enabled in the VB-CABLE panel for Windows' playback slider to affect audio.
  This setting cannot be inferred from endpoint scalar readback. Actual Windows
  driver/audio behavior remains unverified; no Windows software was installed.
- Downmix defaults to front-channel unity with attenuated centre/surround
  contributions and LFE excluded. Optional -3 dB headroom or conservative peak
  normalization is selectable. Mono summing uses explicit coefficients. Existing
  custom matrices are not migrated; reload and apply a preset to change them.
  Loud summed peaks can still clip at the native clamp; use headroom as needed.
- Linux device volume/mute now checks native server readback. PipeWire 1.0+
  latency targets require explicit per-route restart permission and remain server
  buffering requests, not acoustic alignment. Older servers capability-gate them.
  Linux custom matrices, per-route gain and acoustic calibration remain absent.
- Full Python/Qt suite: 174 passed, 13 skipped. Native GNU C++20 PCM tests passed.
  Ruff check/format and git diff checks passed.
- Real private PipeWire 1.0.5 integration: 3 passed, covering volume/mute readback,
  latency request/restoration, fan-out/mixing with PCM, GUI, daemon restart and
  cleanup. No physical speaker/microphone path was tested.
- Linux tar.gz and .deb rebuilt. Extracted portable GUI/FFT smoke (explicit mock)
  passed with PYTHONPATH removed; current logo verified; both SHA256 checks passed.
  This local runtime uses Ubuntu 24.04/glibc 2.39. Windows rebuild requires CI.
