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

Application sources and live channel configuration (2026-11-01):

- Added Windows application session discovery and public process-loopback
  activation for Windows build 20348+, with process creation-time identity,
  self/ancestor capture prevention and original-output duplication checks. These
  are additive version-1 extensions to bridge ABI 2. The new Windows C++ code
  has NOT been compiled or hardware tested in this environment: no Windows
  compiler is installed, and no software was installed for this work.
- Existing Windows Python ran 56 simulated backend/channel/device tests successfully.
  Read-only OS/API inspection found build 26300 and the async activation export;
  this does not verify the new DLL or real application capture. All test caches
  and temporary test files were kept on the Linux filesystem.
- Linux now discovers actual application streams through pw-dump and copies them
  with owned pw-link connections, keeping original playback intact. The local
  Pulse peer PID must belong to the same native PipeWire graph. Unity channel
  remapping/duplication updates only the selected route's links. Non-unity gain
  and additional delay on this graph transport are explicitly rejected.
- Source filtering and per-route Channels actions use backend state. Compatible
  Windows float paths/custom matrices support atomic immutable live-map changes;
  older native bridges retain the explicit restart fallback. Channel-count or
  incompatible source-format changes still require negotiation/restart.
- Full Linux Python/Qt suite: 187 passed, 14 skipped. Ruff check and format passed.
  Native GNU C++20 PCM/ring/concurrency/clock-correction tests passed.
- Real private-server integration: 4 passed on PipeWire 1.0.5 and 4 passed on
  PipeWire 0.3.48, covering actual PCM copies, original-output preservation,
  unrelated-application exclusion, live channel swap, fan-out, profile/resource
  reconciliation, process reconnect, GUI and cleanup. These tests use isolated
  virtual sinks, not physical speakers or microphones.
- Linux portable tar.gz and Debian package rebuilt with bundled Python/Qt; SHA256
  checks passed. The rebuilt frozen GUI also passed real-backend application
  discovery inside the isolated PipeWire 1.0.5 test. Local packages require
  Ubuntu 24.04/glibc 2.39 or compatible.
  No Windows executable was generated locally; use the manual Windows workflow
  to compile and test the updated bridge before trying application capture.

Supplied PNG branding and Orange default (2026-11-01):

- Replaced the recreated SVG assets with the exact supplied clean logo.png, stored
  as a2router/assets/a2router.png. Source and bundled asset SHA256 match. Window,
  application and tray icons share this asset; Windows ICO generation preserves
  its proportions at seven sizes. Linux desktop packaging installs the PNG in
  /usr/share/pixmaps. README displays it at 128 pixels wide.
- Orange is the default for new preferences, with an orange accent and warm dark
  surfaces. Existing saved theme selections and the other theme options remain.
- Full Python/Qt suite: 188 passed, 14 skipped. Ruff check/format and git diff
  checks passed. Isolated new-preference GUI smoke confirmed Orange/#ff9600 and
  nonempty application/window icons. All seven generated ICO PNG entries decoded
  successfully on Linux. No Windows software was installed or changed.
- Linux tar.gz and .deb rebuilt; both SHA256 checks passed. The portable archive
  contains the byte-identical supplied PNG and no superseded SVG logos.

Windows SDK GUID declaration build fix (2026-11-01):

- Moved COM GUID declarations ahead of audio/process-capture headers in the
  bridge, addressing the reported SDK 26100 cguid.h C2059 __uuidof expansion.
  initguid.h remains first to preserve required property-key definitions.
- Full Linux Python/Qt suite: 188 passed, 14 skipped. Native GNU C++20 core
  tests, Ruff and git diff checks passed. MSVC compilation must be verified by
  rerunning the manual Windows workflow; no Windows compiler was installed and
  no Windows settings, drivers or software were changed.

Branding follow-up: mark-only icons and upgrade theme activation (2026-11-01):

- The prior change preserved existing saved themes, so upgraded installations could
  still open in Dark/System. This update migrates existing preferences to Orange
  once, records orangeBrandingV1, and preserves choices made afterwards. A Qt
  regression test starts with a saved Dark preference, verifies the orange
  highlight, then verifies a newly chosen Dark theme survives restart.
- Application, tray, executable/setup and Linux desktop icons now use only the
  original PNG's orbital-A mark, cropped without redrawing it. The complete
  supplied PNG is retained byte-for-byte as assets/wordmark.png for README
  branding at 128 pixels wide. No SVG reconstruction is used.
- Full Python/Qt suite: 188 passed, 14 skipped. Ruff and diff checks passed.
  Seven mark-only ICO sizes decoded successfully. Linux tar.gz/.deb rebuilt,
  both checksum checks passed, and both PNG variants verified in the archive.
